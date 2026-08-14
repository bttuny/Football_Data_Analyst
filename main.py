from datetime import datetime
import pandas as pd
from src.database import (
    init_db, SessionLocal, League, Match, 
    MatchPrediction, PredictionEvaluation, save_prediction
)
from src.data_fetcher import FootballDataFetcher
from src.model import PremierLeaguePoissonModel
from src.evaluation import calculate_brier_score, calculate_log_loss

def run_pipeline():
    print("=== PL xG PREDICTOR & EVALUATION PIPELINE ===")
    
    init_db()
    db = SessionLocal()

    # Confirm that the Premier League exists in the database
    pl_league = db.query(League).filter(League.code == 'ENG-PL').first()

    fetcher = FootballDataFetcher()
    
   # -------------------------------------------------------------
    # VAIHE 1: Päättyneiden otteluiden tulosten päivitys & evaluointi
    # -------------------------------------------------------------
    print("\n1. Tarkistetaan päättyneet ottelut ja evaluoidaan ennusteet...")
    
    df_current_finished, upcoming_matches = fetcher.fetch_premier_league_matches(season=2026)
    
    locked_matches = db.query(Match).filter(Match.status == 'LOCKED').all()
    evaluations_count = 0

    # Tarkistetaan vain jos pelattuja otteluita on saatavilla ja kannassa on lukittuja pelejä
    if not df_current_finished.empty and locked_matches:
        for match in locked_matches:
            match_data = df_current_finished[
                (df_current_finished['home_team'] == match.home_team) & 
                (df_current_finished['away_team'] == match.away_team)
            ]
            
            if not match_data.empty:
                row = match_data.iloc[0]
                actual_home = int(row['home_goals'])
                actual_away = int(row['away_goals'])
                
                match.actual_home_goals = actual_home
                match.actual_away_goals = actual_away
                match.status = 'FINISHED'
                
                pred = db.query(MatchPrediction).filter(
                    MatchPrediction.match_id == match.match_id
                ).order_by(MatchPrediction.created_at.desc()).first()
                
                if pred:
                    brier = calculate_brier_score(
                        float(pred.prob_home_win), float(pred.prob_draw), float(pred.prob_away_win),
                        actual_home, actual_away
                    )
                    loss = calculate_log_loss(
                        float(pred.prob_home_win), float(pred.prob_draw), float(pred.prob_away_win),
                        actual_home, actual_away
                    )
                    
                    pred_outcome = 'H' if pred.prob_home_win > max(pred.prob_draw, pred.prob_away_win) else ('D' if pred.prob_draw > pred.prob_away_win else 'A')
                    actual_outcome = 'H' if actual_home > actual_away else ('D' if actual_home == actual_away else 'A')
                    is_correct = (pred_outcome == actual_outcome)
                    
                    eval_obj = PredictionEvaluation(
                        match_id=match.match_id,
                        prediction_id=pred.prediction_id,
                        brier_score=brier,
                        log_loss=loss,
                        outcome_correct=is_correct
                    )
                    db.add(eval_obj)
                    evaluations_count += 1
                    print(f"   [EVAL] {match.home_team} {actual_home}-{actual_away} {match.away_team} | Brier: {brier} | Correct: {is_correct}")

        db.commit()
    
    print(f"   -> Evaluointi valmis. Päivitetty {evaluations_count} uutta tulosta.")

    # -------------------------------------------------------------
    # VAIHE 2: Teach the Poisson xG model using past and current season data
    # -------------------------------------------------------------
    print("\n2. Koulutetaan Poisson xG -malli...")
    
    # Search for past season matches (2025) to use as training data
    df_past, _ = fetcher.fetch_premier_league_matches(season=2025)
    
    # Combine past season data with current finished matches for training
    if not df_current_finished.empty:
        df_train = pd.concat([df_past, df_current_finished], ignore_index=True)
    else:
        df_train = df_past

    model = PremierLeaguePoissonModel()
    model.fit(df_train)
    print(f"   - Opetusmateriaali: {len(df_train)} ottelua. Kotikeskiarvo: {model.league_avg_home_goals:.2f}")

 # -------------------------------------------------------------
    # VAIHE 3: Tulevien otteluiden ennustaminen (UUSITTU LOGIIKKA)
    # -------------------------------------------------------------
    print("\n3. Lasketaan tuoreet ennusteet tuleville otteluille...")
    sample_upcoming = upcoming_matches[:5]

    for match_data in sample_upcoming:
        home_team = match_data["home_team"]
        away_team = match_data["away_team"]

        match_obj = db.query(Match).filter(
            Match.home_team == home_team,
            Match.away_team == away_team,
            Match.league_id == pl_league.league_id
        ).first()

        # Jos ottelua ei ole vielä kannassa, luodaan se
        if not match_obj:
            match_obj = Match(
                league_id=pl_league.league_id,
                season="2026/2027",
                home_team=home_team,
                away_team=away_team,
                match_datetime=datetime.fromisoformat(match_data["datetime"].replace("Z", "+00:00")),
                status="SCHEDULED"
            )
            db.add(match_obj)
            db.commit()
            db.refresh(match_obj)

        # Lasketaan ja päivitetään ennuste aina, jos peliä ei ole vielä pelattu (status != 'FINISHED')
        if match_obj.status in ["SCHEDULED", "LOCKED"]:
            pred = model.predict_match(home_team, away_team)
            save_prediction(pred, match_obj.match_id)
            print(f"   -> Uusi ennuste laskettu: {home_team} vs {away_team} (xG: {pred['expected_goals_home']}-{pred['expected_goals_away']} | Kotivoitto: {pred['prob_home_win']*100:.1f}%)")

    db.close()
    print("\n=== PIPELINE VALMIS ===")

if __name__ == "__main__":
    run_pipeline()