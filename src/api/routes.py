# src/api/routes.py
from fastapi import FastAPI, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional

from src.core.config import LEAGUES_CONFIG
from src.core.database import get_db, Base, engine
from src.models.entities import Match, MatchPrediction, League
from src.ingestion.odds_fetcher import OddsFetcher, clean_team_name
from src.ingestion.historical_data import CardsDataFetcher
from src.quant.value_finder import calculate_value_bets
from src.quant.cards_model import PremierLeagueCardsModel
from src.services.bankroll_service import BankrollService

from zoneinfo import ZoneInfo
from datetime import timezone

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Top 5 Leagues Quant Analytics API")
templates = Jinja2Templates(directory="templates")

# Alustetaan korttimallit jokaiselle liigalle erikseen
cards_fetcher = CardsDataFetcher()
league_cards_models = {}
for code, conf in LEAGUES_CONFIG.items():
    c_model = PremierLeagueCardsModel()
    c_df = cards_fetcher.fetch_cards_history(league_csv=conf["csv_code"])
    c_model.fit(c_df)
    league_cards_models[code] = c_model


@app.get("/api/v1/predictions/upcoming")
def get_upcoming_predictions(
    league: Optional[str] = None, db: Session = Depends(get_db)
):
    query = (
        db.query(Match)
        .filter(Match.status.in_(["SCHEDULED", "LOCKED"]))
        .order_by(Match.match_datetime.asc())
    )

    if league and league != "ALL":
        query = query.join(League).filter(League.code == league)

    matches = query.limit(50).all()

    odds_fetcher = OddsFetcher()
    current_odds_by_sport = {}

    results = []
    for m in matches:
        l_code = m.league.code if m.league else "PL"
        sport_key = LEAGUES_CONFIG.get(l_code, {}).get(
            "odds_key", "soccer_epl"
        )

        if sport_key not in current_odds_by_sport:
            current_odds_by_sport[sport_key] = odds_fetcher.fetch_current_odds(
                sport_key=sport_key
            )

        events_list = current_odds_by_sport[sport_key]
        match_odds = odds_fetcher.get_odds_for_match(
            m.home_team, m.away_team, events_list, sport_key
        )

        latest_pred = (
            db.query(MatchPrediction)
            .filter(MatchPrediction.match_id == m.match_id)
            .order_by(MatchPrediction.created_at.desc())
            .first()
        )

        if latest_pred:
            prob_h = float(latest_pred.prob_home_win)
            prob_d = float(latest_pred.prob_draw)
            prob_a = float(latest_pred.prob_away_win)

            value_analysis = calculate_value_bets(
                prob_h,
                prob_d,
                prob_a,
                match_odds.get("H", 0.0),
                match_odds.get("D", 0.0),
                match_odds.get("A", 0.0),
            )

            c_model = league_cards_models.get(l_code, PremierLeagueCardsModel())
            card_pred = c_model.predict_cards(
                m.home_team, m.away_team, referee=m.referee
            )

            for vb in value_analysis:
                if vb["is_value"]:
                    BankrollService.place_value_bet(
                        db=db,
                        match_id=m.match_id,
                        match_name=f"{m.home_team} vs {m.away_team}",
                        outcome=vb["outcome"],
                        odds=vb["odds"],
                        ev_pct=vb["ev_percentage"],
                        stake_pct=vb["kelly_stake_pct"],
                        league_code=l_code,
                        market_type="1X2",
                    )

            formatted_time = ""
            if m.match_datetime:
                dt_utc = m.match_datetime
                if dt_utc.tzinfo is None:
                    dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                dt_helsinki = dt_utc.astimezone(ZoneInfo("Europe/Helsinki"))
                formatted_time = dt_helsinki.strftime("%d.%m. klo %H:%M")

            results.append({
                "match_id": m.match_id,
                "league_code": l_code,
                "league_name": m.league.name if m.league else "Valioliiga",
                "match_datetime": formatted_time,
                "home_team": m.home_team,
                "away_team": m.away_team,
                "expected_goals": {
                    "home": float(latest_pred.predicted_home_xg),
                    "away": float(latest_pred.predicted_away_xg),
                },
                "probabilities": {
                    "home_win": prob_h,
                    "draw": prob_d,
                    "away_win": prob_a,
                },
                "odds": match_odds,
                "value_analysis": value_analysis,
                "cards_analysis": card_pred,
            })
    return results


@app.get("/", response_class=HTMLResponse)
def render_dashboard(
    request: Request, league: str = "ALL", db: Session = Depends(get_db)
):
    predictions = get_upcoming_predictions(league=league, db=db)
    return templates.TemplateResponse(
        request,
        "views/dashboard.html",
        {
            "predictions": predictions,
            "active_tab": "matches",
            "current_league": league,
            "leagues_config": LEAGUES_CONFIG,
        },
    )


@app.get("/bankroll", response_class=HTMLResponse)
def render_bankroll(request: Request, db: Session = Depends(get_db)):
    summary = BankrollService.get_portfolio_summary(db)
    return templates.TemplateResponse(
        request,
        "views/bankroll.html",
        {"summary": summary, "active_tab": "bankroll"},
    )


@app.post("/api/v1/bets/cards")
def place_card_bet(
    match_id: int = Form(...),
    match_name: str = Form(...),
    league_code: str = Form("PL"),
    selected_line: float = Form(3.5),
    user_odds: float = Form(...),
    line_prob: float = Form(...),
    db: Session = Depends(get_db)
):
    if user_odds > 1.0 and line_prob > 0:
        ev = (line_prob * user_odds) - 1.0
        b = user_odds - 1.0
        kelly = ((b * line_prob) - (1.0 - line_prob)) / b if b > 0 else 0
        stake_pct = min(2.0, round(max(0.0, kelly * 0.25) * 100, 1))

        if ev > 0.02 and stake_pct >= 0.1:
            market_type = f"CARDS_OVER_{str(selected_line).replace('.', '_')}"
            BankrollService.place_value_bet(
                db=db,
                match_id=match_id,
                match_name=match_name,
                outcome=f"Yli {selected_line}",
                odds=user_odds,
                ev_pct=round(ev * 100, 1),
                stake_pct=stake_pct,
                league_code=league_code,
                market_type=market_type
            )
    return RedirectResponse(url="/bankroll", status_code=303)