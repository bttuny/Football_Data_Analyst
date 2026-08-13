import pandas as pd
from datetime import datetime
from src.database import init_db, SessionLocal, League, Match, MatchPrediction, save_prediction
from src.data_fetcher import FootballDataFetcher
from src.model import PremierLeaguePoissonModel

def run_pipeline():
    print("=== PL xG Prediction Pipeline ===")

    init_db()
    db = SessionLocal()
    pl_league = db.query(League).filter(League.code == "ENG-PL").first()
    if not pl_league:
        pl_league = League(name="Premier League", country="England", code="ENG-PL")
        db.add(pl_league)
        db.commit()
        db.refresh(pl_league)

    print("Fetching Premier League match data...")
    fetcher = FootballDataFetcher()
    df_finished, upcoming_matches = fetcher.fetch_premier_league_matches(season=2025)
    df_current_finished, upcoming_matches = fetcher.fetch_premier_league_matches(season=2026)

    if not df_current_finished.empty:
        df_finished = pd.concat([df_finished, df_current_finished], ignore_index=True)

    print(f"Fetched {len(df_finished)} finished matches and {len(upcoming_matches)} upcoming matches.")

    if df_finished.empty:
        print("No finished matches found. Exiting.")
        db.close()
        return

    print("Fitting the Poisson model...")
    model = PremierLeaguePoissonModel()
    model.fit(df_finished)
    print(f"Model fitted. League averages - Home: {model.league_avg_home_goals:.2f}, Away: {model.league_avg_away_goals:.2f}")

    print("Predicting upcoming matches...")
    sample_upcoming = upcoming_matches[:5]

    for match in sample_upcoming:
        home_team = match['home_team']
        away_team = match['away_team']

        match_obj = db.query(Match).filter(
           Match.home_team == home_team,
           Match.away_team == away_team,
           Match.league_id == pl_league.league_id,
        ).first()

        if not match_obj:
            match_obj = Match(
                league_id=pl_league.league_id,
                season = "2025/2026",
                home_team=home_team,
                away_team=away_team,
                match_datetime=datetime.fromisoformat(match['datetime'].replace('Z', '+00:00')),
                status="SCHEDULED"
            )
            db.add(match_obj)
            db.commit()
            db.refresh(match_obj)

        pred = model.predict_match(home_team, away_team)
        save_prediction(pred, match_obj.match_id)

        print(f"   -> Ennustettu: {home_team} vs {away_team}")
        print(f"      xG: {pred['expected_goals_home']} - {pred['expected_goals_away']} | "
              f"1X2: {pred['prob_home_win']*100:.1f}% - {pred['prob_draw']*100:.1f}% - {pred['prob_away_win']*100:.1f}%")

        db.close()
        print("Pipeline completed successfully.")

if __name__ == "__main__":
    run_pipeline()

