# src/api/routes.py
from fastapi import FastAPI, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.core.database import get_db, Base, engine
from src.models.entities import Match, MatchPrediction
from src.ingestion.odds_fetcher import OddsFetcher, clean_team_name
from src.ingestion.historical_data import CardsDataFetcher
from src.quant.value_finder import calculate_value_bets
from src.quant.cards_model import PremierLeagueCardsModel
from src.services.bankroll_service import BankrollService

# Luodaan taulut varmuudella
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Quant Sports Analytics API")
templates = Jinja2Templates(directory="templates")

# Alustetaan ja opetetaan korttimalli
cards_fetcher = CardsDataFetcher()
df_cards = cards_fetcher.fetch_cards_history()
cards_model = PremierLeagueCardsModel()
cards_model.fit(df_cards)


@app.get("/api/v1/predictions/upcoming")
def get_upcoming_predictions(db: Session = Depends(get_db)):
    matches = (
        db.query(Match)
        .filter(Match.status.in_(["SCHEDULED", "LOCKED"]))
        .order_by(Match.match_datetime.asc())
        .limit(10)
        .all()
    )

    odds_fetcher = OddsFetcher()
    current_odds = odds_fetcher.fetch_current_odds()
    results = []

    for m in matches:
        latest_pred = (
            db.query(MatchPrediction)
            .filter(MatchPrediction.match_id == m.match_id)
            .order_by(MatchPrediction.created_at.desc())
            .first()
        )

        if latest_pred:
            clean_key = f"{clean_team_name(m.home_team)} vs {clean_team_name(m.away_team)}"
            match_odds = current_odds.get(
                clean_key, {"H": 0.0, "D": 0.0, "A": 0.0}
            )

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
            card_pred = cards_model.predict_cards(m.home_team, m.away_team, referee=m.referee)

            # Automaattinen Paper Betin asetus, jos ylikerroin löytyy
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
                    )

            results.append({
                "match_id": m.match_id,
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
def render_dashboard(request: Request, db: Session = Depends(get_db)):
    predictions = get_upcoming_predictions(db)
    return templates.TemplateResponse(
        request,
        "views/dashboard.html",
        {"predictions": predictions, "active_tab": "matches"},
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
    user_odds: float = Form(...),
    prob_over_3_5: float = Form(...),
    db: Session = Depends(get_db),
):
    if user_odds > 1.0 and prob_over_3_5 > 0:
        ev = (prob_over_3_5 * user_odds) - 1.0

        # Kelly panos
        b = user_odds - 1.0
        kelly = (b * prob_over_3_5 - (1.0 - prob_over_3_5)) / b if b > 0 else 0
        stake_pct = min(2.0, round(max(0.0, kelly * 0.25) * 100, 1))

        if ev > 0.02 and stake_pct >= 0.1:
            BankrollService.place_value_bet(
                db=db,
                match_id=match_id,
                match_name=match_name,
                outcome="Yli 3.5",
                odds=user_odds,
                ev_pct=round(ev * 100, 1),
                stake_pct=stake_pct,
                market_type="CARDS_OVER_3_5",
            )
    return RedirectResponse(url="/bankroll", status_code=303)