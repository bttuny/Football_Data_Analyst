# src/api.py
import re
from typing import List
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.database import SessionLocal, Match, MatchPrediction, PredictionEvaluation
from src.odds_fetcher import OddsFetcher, clean_team_name
from src.value_calculator import calculate_value_bets
from src.cards_data_fetcher import CardsDataFetcher
from src.cards_model import PremierLeagueCardsModel

app = FastAPI(
    title="Premier League Value Betting & Cards Engine API",
    description="REST API maaliodottamille, ylikertoimille ja korttitilastoille.",
    version="1.0.0"
)

# Koulutetaan korttimalli heti taustalle
cards_fetcher = CardsDataFetcher()
df_cards = cards_fetcher.fetch_cards_history()
cards_model = PremierLeagueCardsModel()
cards_model.fit(df_cards)

templates = Jinja2Templates(directory="templates")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/api/v1/predictions/upcoming", summary="Hae tulevat ennusteet, kertoimet ja kortit")
def get_upcoming_predictions(db: Session = Depends(get_db)):
    matches = (
        db.query(Match)
        .filter(Match.status.in_(['SCHEDULED', 'LOCKED']))
        .order_by(Match.match_datetime.asc())
        .limit(10)
        .all()
    )
    
    odds_fetcher = OddsFetcher()
    current_odds = odds_fetcher.fetch_current_odds()
    
    results = []

    for m in matches:
        latest_pred = db.query(MatchPrediction).filter(
            MatchPrediction.match_id == m.match_id
        ).order_by(MatchPrediction.created_at.desc()).first()

        if latest_pred:
            clean_match_key = f"{clean_team_name(m.home_team)} vs {clean_team_name(m.away_team)}"
            match_odds = current_odds.get(clean_match_key, {"H": 0.0, "D": 0.0, "A": 0.0})

            prob_h = float(latest_pred.prob_home_win)
            prob_d = float(latest_pred.prob_draw)
            prob_a = float(latest_pred.prob_away_win)

            value_analysis = calculate_value_bets(
                prob_h, prob_d, prob_a,
                match_odds.get("H", 0.0), match_odds.get("D", 0.0), match_odds.get("A", 0.0)
            )

            # Lasketaan korttianalyysi oikealla mallilla
            card_pred = cards_model.predict_cards(m.home_team, m.away_team)

            results.append({
                "match_id": m.match_id,
                "home_team": m.home_team,
                "away_team": m.away_team,
                "expected_goals": {
                    "home": float(latest_pred.predicted_home_xg),
                    "away": float(latest_pred.predicted_away_xg)
                },
                "probabilities": {
                    "home_win": prob_h,
                    "draw": prob_d,
                    "away_win": prob_a
                },
                "odds": match_odds,
                "value_analysis": value_analysis,
                "cards_analysis": card_pred  # <-- Varmistettu, että tämä on mukana
            })
    return results


@app.get("/", response_class=HTMLResponse, summary="Käyttöliittymä-Dashboard")
def render_dashboard(request: Request, db: Session = Depends(get_db)):
    predictions = get_upcoming_predictions(db)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"predictions": predictions}
    )