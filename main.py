# main.py
from datetime import datetime
import pandas as pd
from src.core.config import LEAGUES_CONFIG
from src.core.database import SessionLocal, Base, engine
from src.models.entities import (
    League,
    Match,
    MatchPrediction,
    PredictionEvaluation,
)
from src.ingestion.football_data import FootballDataFetcher
from src.quant.poisson_dixon import PremierLeaguePoissonModel
from src.quant.metrics import calculate_brier_score, calculate_log_loss
from src.services.bankroll_service import BankrollService


def run_pipeline():
    print("=== TOP 5 LEAGUES QUANT ANALYST & BANKROLL PIPELINE ===")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    fetcher = FootballDataFetcher()

    for code, conf in LEAGUES_CONFIG.items():
        print(f"\n--- Käsitellään {conf['name']} ({code}) ---")

        # 1. Varmistetaan liiga tietokannassa
        league_obj = db.query(League).filter(League.code == code).first()
        if not league_obj:
            league_obj = League(
                name=conf["name"], code=code, country=conf["country"]
            )
            db.add(league_obj)
            db.commit()
            db.refresh(league_obj)

        # 2. Haetaan ottelut
        df_prev, _ = fetcher.fetch_matches(
            competition_code=conf["football_data_code"], season=2025
        )
        df_curr, upcoming = fetcher.fetch_matches(
            competition_code=conf["football_data_code"], season=2026
        )

        # 3. Ratkaistaan pelatut pelit ja evaluoidaan
        locked_matches = (
            db.query(Match)
            .filter(
                Match.league_id == league_obj.league_id, Match.status == "LOCKED"
            )
            .all()
        )
        if not df_curr.empty and locked_matches:
            for match in locked_matches:
                m_data = df_curr[
                    (df_curr["home_team"] == match.home_team)
                    & (df_curr["away_team"] == match.away_team)
                ]
                if not m_data.empty:
                    row = m_data.iloc[0]
                    act_h, act_a = int(row["home_goals"]), int(
                        row["away_goals"]
                    )
                    match.actual_home_goals = act_h
                    match.actual_away_goals = act_a
                    match.status = "FINISHED"

                    BankrollService.settle_bets_for_match(
                        db, match.match_id, act_h, act_a
                    )

                    pred = (
                        db.query(MatchPrediction)
                        .filter(MatchPrediction.match_id == match.match_id)
                        .order_by(MatchPrediction.created_at.desc())
                        .first()
                    )
                    if pred:
                        brier = calculate_brier_score(
                            float(pred.prob_home_win),
                            float(pred.prob_draw),
                            float(pred.prob_away_win),
                            act_h,
                            act_a,
                        )
                        loss = calculate_log_loss(
                            float(pred.prob_home_win),
                            float(pred.prob_draw),
                            float(pred.prob_away_win),
                            act_h,
                            act_a,
                        )
                        pred_out = (
                            "H"
                            if pred.prob_home_win
                            > max(pred.prob_draw, pred.prob_away_win)
                            else (
                                "D"
                                if pred.prob_draw > pred.prob_away_win
                                else "A"
                            )
                        )
                        act_out = (
                            "H"
                            if act_h > act_a
                            else ("D" if act_h == act_a else "A")
                        )

                        eval_obj = PredictionEvaluation(
                            match_id=match.match_id,
                            prediction_id=pred.prediction_id,
                            brier_score=brier,
                            log_loss=loss,
                            outcome_correct=(pred_out == act_out),
                        )
                        db.add(eval_obj)
            db.commit()

        # 4. Koulutetaan sarjakohtainen Dixon-Coles
        training_data = pd.concat([df_prev, df_curr], ignore_index=True)
        model = PremierLeaguePoissonModel()
        model.fit(training_data)

        # 5. Ennustetaan tulevat
        for m_data in upcoming:
            h, a = m_data["home_team"], m_data["away_team"]
            match_obj = (
                db.query(Match)
                .filter(
                    Match.home_team == h,
                    Match.away_team == a,
                    Match.league_id == league_obj.league_id,
                )
                .first()
            )
            if not match_obj:
                match_obj = Match(
                    league_id=league_obj.league_id,
                    season="2026/2027",
                    home_team=h,
                    away_team=a,
                    match_datetime=datetime.fromisoformat(
                        m_data["datetime"].replace("Z", "+00:00")
                    ),
                    referee=m_data.get("referee"),
                    status="SCHEDULED",
                )
                db.add(match_obj)
                db.commit()
                db.refresh(match_obj)

            if match_obj.status in ["SCHEDULED", "LOCKED"]:
                pred = model.predict_match(h, a)
                new_pred = MatchPrediction(
                    match_id=match_obj.match_id,
                    predicted_home_xg=pred["expected_goals_home"],
                    predicted_away_xg=pred["expected_goals_away"],
                    prob_home_win=pred["prob_home_win"],
                    prob_draw=pred["prob_draw"],
                    prob_away_win=pred["prob_away_win"],
                )
                db.add(new_pred)
                match_obj.status = "LOCKED"
                db.commit()

    db.close()
    print("\n=== KAIKKI TOP 5 LIIGAT KÄSITELTY ONNISTUNEESTI ===")


if __name__ == "__main__":
    run_pipeline()