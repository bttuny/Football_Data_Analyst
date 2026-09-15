import pandas as pd
import os
from sqlalchemy.orm  import Session

from src.core.database import SessionLocal
from src.models.entities import Match

def build_training_dataset():
    db: Session = SessionLocal()

    matches = db.query(Match).filter(
        Match.status == "FINISHED"
    ).order_by(Match.match_datetime.asc()).all()

    team_stats = {}
    ml_data = []

    for match in matches:
        home_xg_avg = 0.0
        home_xga_avg = 0.0
        home_gf_avg = 0.0
        home_ga_avg = 0.0

        away_xg_avg = 0.0
        away_xga_avg = 0.0
        away_gf_avg = 0.0
        away_ga_avg = 0.0

        if match.home_xg is None or match.away_xg is None or match.actual_home_goals is None or match.actual_away_goals is None:
            continue

        home = match.home_team
        away = match.away_team


        if home not in team_stats:
            team_stats[home] = []
        if away not in team_stats:
            team_stats[away] = []


        if len(team_stats[home]) >= 5 and len(team_stats[away]) >= 5:
            home_last_5 = team_stats[home][-5:]
            away_last_5 = team_stats[away][-5:]

            home_xg_avg = sum([x['xg_for'] for x in home_last_5]) / 5
            home_xga_avg = sum([x['xg_against'] for x in home_last_5]) / 5
            home_gf_avg = sum([x['goals_for'] for x in home_last_5]) / 5
            home_ga_avg = sum([x['goals_against'] for x in home_last_5]) / 5

            away_xg_avg = sum([x['xg_for'] for x in away_last_5]) / 5
            away_xga_avg = sum([x['xg_against'] for x in away_last_5]) / 5
            away_gf_avg = sum([x['goals_for'] for x in away_last_5]) / 5
            away_ga_avg = sum([x['goals_against'] for x in away_last_5]) / 5

        if match.actual_home_goals > match.actual_away_goals:
            target = 2
        elif match.actual_home_goals == match.actual_away_goals:
            target = 1
        else:
            target = 0

        ml_data.append({
            'match_id': match.match_id,
            'league_id': match.league_id,
            'home_team': home,
            'away_team': away,
            'home_xg_avg_5': round(home_xg_avg, 3),
            'home_xga_avg_5': round(home_xga_avg, 3),
            'home_gf_avg_5': round(home_gf_avg, 3),
            'home_ga_avg_5': round(home_ga_avg, 3),
            'away_xg_avg_5': round(away_xg_avg, 3),
            'away_xga_avg_5': round(away_xga_avg, 3),
            'away_gf_avg_5': round(away_gf_avg, 3),
            'away_ga_avg_5': round(away_ga_avg, 3),
            'target': target
        })

        team_stats[home].append({
            'xg_for': match.home_xg,
            'xg_against': match.away_xg,
            'goals_for': match.actual_home_goals,
            'goals_against': match.actual_away_goals
        })

        team_stats[away].append({
            'xg_for': match.away_xg,
            'xg_against': match.home_xg,
            'goals_for': match.actual_away_goals,
            'goals_against': match.actual_home_goals
        })
    db.close()

    df = pd.DataFrame(ml_data)
    print(f"Dataset luotu onnistuneesti! Yhteensä {len(df)} opetuskelpoista ottelua.")

    os.makedirs("data", exist_ok=True)
    file_path = "data/ml_training_data.csv"
    df.to_csv(file_path, index=False)
    print(f"Opetusdata tallennettu polkuun: {file_path}")
    
    return df

if __name__ == "__main__":
    build_training_dataset()