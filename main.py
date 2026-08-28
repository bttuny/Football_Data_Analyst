# main.py
import os
from datetime import datetime, timezone
import pandas as pd
from sqlalchemy.exc import IntegrityError

from src.core.config import LEAGUES_CONFIG
from src.core.database import SessionLocal, Base, engine
from src.models.entities import (
    League,
    Match,
    MatchPrediction,
    PredictionEvaluation,
    CardsModelCache,
)
from src.ingestion.football_data import FootballDataFetcher
from src.ingestion.historical_data import CardsDataFetcher
from src.quant.poisson_dixon import PremierLeaguePoissonModel
from src.quant.metrics import calculate_brier_score, calculate_log_loss
from src.quant.cards_model import PremierLeagueCardsModel, clean_name
from src.services.bankroll_service import BankrollService


def run_pipeline():
    print("=== TOP 5 LEAGUES QUANT ANALYST & BANKROLL PIPELINE ===")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    fetcher = FootballDataFetcher()
    cards_fetcher = CardsDataFetcher()
    
    os.makedirs("data", exist_ok=True)

    for code, conf in LEAGUES_CONFIG.items():
        print(f"\n--- Käsitellään {conf['name']} ({code}) ---")

        # 1. Lataa ja tallenna kortti- ja tuomaridata
        print("Ladataan kortti- ja tuomaridata...")
        cards_df = cards_fetcher.fetch_cards_history(league_csv=conf["csv_code"])
        if not cards_df.empty:
            # Vältetään fragmentaatiovaroitus .assign() metodilla
            cards_df = cards_df.assign(
                HomeClean=cards_df["HomeTeam"].apply(clean_name),
                AwayClean=cards_df["AwayTeam"].apply(clean_name)
            )
            cards_df.to_csv(f"data/{code}_cards.csv", index=False)
            print(f"✅ Korttidata ({len(cards_df)} ottelua) tallennettu cacheen.")

            # Opetetaan korttimalli ja tallennetaan parametrit tietokantaan
            cards_model = PremierLeagueCardsModel()
            cards_model.fit(cards_df)

            cache = db.query(CardsModelCache).filter(CardsModelCache.league_code == code).first()
            if cache:
                cache.league_avg_cards = cards_model.league_avg_cards
                cache.team_card_factors = cards_model.team_card_factors
                cache.referee_factors = {k: float(v) for k, v in cards_model.referee_factors.items()}
                cache.updated_at = datetime.now(timezone.utc)
            else:
                cache = CardsModelCache(
                    league_code=code,
                    league_avg_cards=cards_model.league_avg_cards,
                    team_card_factors=cards_model.team_card_factors,
                    referee_factors={k: float(v) for k, v in cards_model.referee_factors.items()},
                )
                db.add(cache)
            db.commit()
            print(f"💾 Korttimalli {code} tallennettu tietokantaan.")

        # 2. Varmistetaan liiga
        league_obj = db.query(League).filter(League.code == code).first()
        if not league_obj:
            league_obj = League(
                name=conf["name"], code=code, country=conf["country"]
            )
            db.add(league_obj)
            db.commit()
            db.refresh(league_obj)

        # 3. Haetaan data Dixon-Colesia varten
        df_prev, _ = fetcher.fetch_matches(
            competition_code=conf["football_data_code"], season=2025
        )
        df_curr, upcoming = fetcher.fetch_matches(
            competition_code=conf["football_data_code"], season=2026
        )

        # 4. Ratkaistaan pelatut pelit ja evaluoidaan
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
                    act_h, act_a = int(row["home_goals"]), int(row["away_goals"])
                    match.actual_home_goals = act_h
                    match.actual_away_goals = act_a
                    match.status = "FINISHED"

                    act_cards = None
                    if not cards_df.empty and "Date" in cards_df.columns:
                        c_match = cards_df[
                            (cards_df["HomeClean"] == clean_name(match.home_team)) &
                            (cards_df["AwayClean"] == clean_name(match.away_team))
                        ].copy()
                        if isinstance(c_match, pd.DataFrame) and not c_match.empty:
                            c_match["parsed_date"] = pd.to_datetime(c_match["Date"], dayfirst=True, errors="coerce")
                            c_match = c_match.sort_values(by="parsed_date")
                            last_match = c_match.iloc[-1]
                            
                            # Varmistetaan, ettei oteta viime kauden tulosta (max 4 päivän heitto ottelupäivästä)
                            if pd.notna(last_match["parsed_date"]) and match.match_datetime:
                                m_date = match.match_datetime.replace(tzinfo=None)
                                diff_days = abs((last_match["parsed_date"] - m_date).days)
                                if diff_days <= 4:
                                    act_cards = int(last_match["total_cards"])

                    # Ratkaistaan vedot salkussa
                    BankrollService.settle_bets_for_match(
                        db, match.match_id, act_h, act_a, actual_cards=act_cards
                    )

                    pred = (
                        db.query(MatchPrediction)
                        .filter(MatchPrediction.match_id == match.match_id)
                        .order_by(MatchPrediction.created_at.desc())
                        .first()
                    )
                    
                    if pred:
                        try:
                            # Varmistetaan, ettei evaluointia lisätä kahdesti
                            existing_eval = db.query(PredictionEvaluation).filter(PredictionEvaluation.match_id == match.match_id).first()
                            if not existing_eval:
                                brier = calculate_brier_score(
                                    pred.prob_home_win, pred.prob_draw, pred.prob_away_win,
                                    act_h, act_a,
                                )
                                loss = calculate_log_loss(
                                    pred.prob_home_win, pred.prob_draw, pred.prob_away_win,
                                    act_h, act_a,
                                )
                                pred_out = (
                                    "H" if pred.prob_home_win > max(pred.prob_draw, pred.prob_away_win)
                                    else ("D" if pred.prob_draw > pred.prob_away_win else "A")
                                )
                                act_out = "H" if act_h > act_a else ("D" if act_h == act_a else "A")

                                eval_obj = PredictionEvaluation(
                                    match_id=match.match_id,
                                    prediction_id=pred.prediction_id,
                                    brier_score=brier,
                                    log_loss=loss,
                                    outcome_correct=(pred_out == act_out),
                                )
                                db.add(eval_obj)
                                db.commit()
                        except Exception as e:
                            # DB Virhetilanteessa perutaan transaktio, jottei koko skripti kaadu
                            db.rollback()
                            print(f"  ⚠️ Ohitetaan evaluaation tallennus (tietokantavirhe ottelulle {match.match_id})")
            
            db.commit()

        # 5. Koulutetaan sarjakohtainen Dixon-Coles
        training_data = pd.concat([df_prev, df_curr], ignore_index=True)
        model = PremierLeaguePoissonModel()
        model.fit(training_data)

        # 6. Ennustetaan tulevat
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
            else:
                if m_data.get("referee") and match_obj.referee != m_data.get("referee"):
                    match_obj.referee = m_data.get("referee")
                    db.commit()

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