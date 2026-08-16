# src/api/routes.py
import time
import os
import pandas as pd
import json
from datetime import datetime
from fastapi import FastAPI, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional

from src.core.config import LEAGUES_CONFIG
from src.core.database import get_db, Base, engine
from src.models.entities import Match, MatchPrediction, League
from src.ingestion.odds_fetcher import OddsFetcher
from src.quant.value_finder import calculate_value_bets
from src.quant.cards_model import PremierLeagueCardsModel, clean_name
from src.services.bankroll_service import BankrollService

from zoneinfo import ZoneInfo
from datetime import timezone

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Top 5 Leagues Quant Analytics API")
templates = Jinja2Templates(directory="templates")

# Dynaaminen korttimallien muisti
league_cards_models = {}

ODDS_CACHE = {}
ODDS_CAHCE_TTL = {}
ODDS_CACHE_FILE = "data/odds_cache.json"

def load_odds_cache():
    if os.path.exists(ODDS_CACHE_FILE):
        try:
            with open(ODDS_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_odds_cache(cache_data):
    os.makedirs("data", exist_ok=True)
    with open(ODDS_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache_data, f)

# Ladataan välimuisti heti käynnistyksessä
ODDS_CACHE = load_odds_cache()

def get_last_odds_update_time():
    if not ODDS_CACHE:
        return "Ei kertoimia"
    latest = max([v.get("timestamp", 0) for v in ODDS_CACHE.values()])
    if latest == 0:
        return "Ei kertoimia"
    dt = datetime.fromtimestamp(latest, tz=ZoneInfo("Europe/Helsinki"))
    return dt.strftime("%d.%m. klo %H:%M")

def get_cards_model(code: str) -> PremierLeagueCardsModel:
    """Hakee mallin muistista, tai lataa sen levyltä lennosta jos se puuttuu."""
    model = league_cards_models.get(code)
    
    # KORJAUS: Tarkistetaan, että mallissa on joukkuekertoimia (eikä tuomareita, joita ei kaikissa liigoissa ole)
    if model and len(model.team_card_factors) > 0:
        return model
        
    new_model = PremierLeagueCardsModel()
    file_path = f"data/{code}_cards.csv"
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path)
            if not df.empty:
                new_model.fit(df)
                print(f"✅ Ladattiin korttimalli lennosta liigalle {code}: {len(df)} ottelua.")
        except Exception as e:
            print(f"⚠️ Virhe ladattaessa mallia {code}: {e}")
            
    # Tallennetaan malli välimuistiin, jotta sitä ei ladata turhaan uudelleen
    league_cards_models[code] = new_model
    return new_model

def get_league_referees():
    """Hakee dynaamisesti ladatuista malleista kaikkien liigojen tuomarit."""
    ref_map = {}
    for code in LEAGUES_CONFIG.keys():
        model = get_cards_model(code)
        ref_list = []
        for name, factor in model.referee_factors.items():
            if len(name) > 2:
                ref_list.append({
                    "name": name.title(),
                    "factor": round(float(factor), 2)
                })
        ref_list.sort(key=lambda x: x["name"])
        ref_map[code] = ref_list
    return ref_map

@app.post("/api/v1/odds/refresh")
def refresh_odds(request: Request):
    """Manuaalinen nappi kertoimien päivitykseen."""
    odds_fetcher = OddsFetcher()
    current_time = time.time()
    
    for code, conf in LEAGUES_CONFIG.items():
        sport_key = conf.get("odds_key")
        if sport_key:
            print(f"🔄 Manuaalinen päivitys: {sport_key}...")
            try:
                fetched_data = odds_fetcher.fetch_current_odds(sport_key=sport_key)
                ODDS_CACHE[sport_key] = {
                    "data": fetched_data,
                    "timestamp": current_time
                }
            except Exception as e:
                print(f"⚠️ Virhe haettaessa kertoimia {sport_key}: {e}")
                
    save_odds_cache(ODDS_CACHE)
    # Palautetaan käyttäjä samaan liiganäkymään, jossa hän oli
    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=303)


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
    results = []

    for m in matches:
        l_code = m.league.code if m.league else "PL"
        sport_key = LEAGUES_CONFIG.get(l_code, {}).get("odds_key", "soccer_epl")

        # Jos liigaa ei ole koskaan haettu välimuistiin (esim. ensimmäinen asennus), haetaan kerran
        if sport_key not in ODDS_CACHE:
            print(f"🌐 Ensimmäinen haku liigalle {sport_key}...")
            fetched_data = odds_fetcher.fetch_current_odds(sport_key=sport_key)
            ODDS_CACHE[sport_key] = {
                "data": fetched_data,
                "timestamp": time.time()
            }
            save_odds_cache(ODDS_CACHE)

        events_list = ODDS_CACHE.get(sport_key, {}).get("data", [])
        
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
                prob_h, prob_d, prob_a,
                match_odds.get("H", 0.0), match_odds.get("D", 0.0), match_odds.get("A", 0.0),
            )

            c_model = get_cards_model(l_code)
            card_pred = c_model.predict_cards(m.home_team, m.away_team, referee=m.referee)
            
            h_clean = clean_name(m.home_team)
            a_clean = clean_name(m.away_team)
            h_f = next((v for k, v in c_model.team_card_factors.items() if len(k) > 2 and k in h_clean), 1.0)
            a_f = next((v for k, v in c_model.team_card_factors.items() if len(k) > 2 and k in a_clean), 1.0)
            card_pred["base_lambda"] = round(c_model.league_avg_cards * ((h_f + a_f) / 2.0), 2)

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
                "value_analysis": value_analysis,
                "cards_analysis": card_pred,
            })
    return results


@app.get("/", response_class=HTMLResponse)
def render_dashboard(request: Request, league: str = "ALL", db: Session = Depends(get_db)):
    predictions = get_upcoming_predictions(league=league, db=db)
    referees_by_league = get_league_referees()
    last_updated = get_last_odds_update_time() # Haetaan päivitysaika

    return templates.TemplateResponse(
        request,
        "views/dashboard.html",
        {
            "predictions": predictions,
            "active_tab": "matches",
            "current_league": league,
            "leagues_config": LEAGUES_CONFIG,
            "referees_by_league": referees_by_league,
            "last_updated": last_updated, # Välitetään UI:hin
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