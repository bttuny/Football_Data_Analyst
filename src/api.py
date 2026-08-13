from typing import List
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from src.database import SessionLocal, Match, MatchPrediction, PredictionEvaluation

app = FastAPI(
    title="Premier League xG & Prediction Engine API",
    description="API for Premier League xG predictions and evaluation",
    version="1.0.0",
)

# Dependency to get the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# REST API ENDPOINTS (JSON API)

@app.get("/api/v1/predictions/upcoming", summary="Get upcoming match predictions")
def get_upcoming_predictions(db: Session = Depends(get_db)):
    """
    Get predictions for upcoming matches.
    Returns a list of upcoming matches with their predicted probabilities.
    """
    upcoming_matches = db.query(Match).filter(Match.status == 'LOCKED').all()
    results = []

    for m in upcoming_matches:
        latest_pred = db.query(MatchPrediction).filter(
            MatchPrediction.match_id == m.match_id
            ).order_by(MatchPrediction.created_at.desc()).first()

        if latest_pred:
            results.append({
                "match_id": m.match_id,
                "home_team": m.home_team,
                "away_team": m.away_team,
                "match_datetime": m.match_datetime.isoformat(),
                "expected_goals": {
                    "home": float(latest_pred.predicted_home_xg),
                    "away": float(latest_pred.predicted_away_xg)
                },
                "probabilities": {
                    "home_win": float(latest_pred.prob_home_win),
                    "draw": float(latest_pred.prob_draw),
                    "away_win": float(latest_pred.prob_away_win)
                }
            })

    return results

@app.get("/api/evaluations/summary", summary="Get models performance metrics")
def get_model_evaluations(db: Session = Depends(get_db)):
    """
    Get summary of model evaluations including average Brier score and log loss.
    """
    evals = db.query(PredictionEvaluation).all()
    if not evals:
        return {"message": "No evaluations found."}

    total_evals = len(evals)
    avg_brier = sum(float(e.brier_score) for e in evals) / total_evals
    correct_outcomes = sum(1 for e in evals if e.outcome_correct)



    return {
        "evaluations_count": len(total_evals),
        "average_brier_score": round(avg_brier, 4),
        "accuracy_percentage": round(correct_outcomes / total_evals * 100, 2) if total_evals > 0 else 0
    }


templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse, summary="Käyttöliittymä-Dashboard")
def render_dashboard(request: Request, db: Session = Depends(get_db)):
    predictions = get_upcoming_predictions(db)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"predictions": predictions}
    )