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

    team_stats_all = {}
    team_stats_home = {}
    team_stats_away = {}

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
        home_all_5 = {}
        away_all_5 = {}
        home_all_10 = {}
        away_all_10 = {}
        home_last_5 = {}
        away_last_5 = {}

        if match.home_xg is None or match.away_xg is None or match.actual_home_goals is None or match.actual_away_goals is None:
            continue

        home = match.home_team
        away = match.away_team

        for t in (home, away):
            if t not in team_stats_all:
                team_stats_all[t] = []
                team_stats_home[t] = []
                team_stats_away[t] = []


        if len(team_stats_all[home]) >= 10 and len(team_stats_all[away]) >= 10 and len(team_stats_home[home]) >= 5 and len(team_stats_away[away]) >= 5:
            home_all_5 = team_stats_all[home][-5:]
            away_all_5 = team_stats_all[away][-5:]

            home_all_10 = team_stats_all[home][-10:]
            away_all_10 = team_stats_all[away][-10:]

            home_last_5 = team_stats_home[home][-5:]
            away_last_5 = team_stats_away[away][-5:]

            

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
                
                # Lyhyt vire (Koti)
                'home_xg_avg_5': sum(x['xg_for'] for x in home_all_5) / 5,
                'home_xga_avg_5': sum(x['xg_against'] for x in home_all_5) / 5,
                # Keskipitkä vire (Koti)
                'home_xg_avg_10': sum(x['xg_for'] for x in home_all_10) / 10,
                'home_xga_avg_10': sum(x['xg_against'] for x in home_all_10) / 10,
                # Aito kotivire (Koti)
                'home_true_home_xg_5': sum(x['xg_for'] for x in home_last_5) / 5,
                'home_true_home_xga_5': sum(x['xg_against'] for x in home_last_5) / 5,
                
                # Lyhyt vire (Vieras)
                'away_xg_avg_5': sum(x['xg_for'] for x in away_all_5) / 5,
                'away_xga_avg_5': sum(x['xg_against'] for x in away_all_5) / 5,
                # Keskipitkä vire (Vieras)
                'away_xg_avg_10': sum(x['xg_for'] for x in away_all_10) / 10,
                'away_xga_avg_10': sum(x['xg_against'] for x in away_all_10) / 10,
                # Aito vierasvire (Vieras)
                'away_true_away_xg_5': sum(x['xg_for'] for x in away_last_5) / 5,
                'away_true_away_xga_5': sum(x['xg_against'] for x in away_last_5) / 5,
                
                'target': target
            })

        home_stats = {
            'xg_for': float(match.home_xg),
            'xg_against': float(match.away_xg),
            'goals_for': match.actual_home_goals,
            'goals_against': match.actual_away_goals
        }
        away_stats = {
            'xg_for': float(match.away_xg),
            'xg_against': float(match.home_xg),
            'goals_for': match.actual_away_goals,
            'goals_against': match.actual_home_goals
        }

        team_stats_all[home].append(home_stats)
        team_stats_all[away].append(away_stats)

        team_stats_home[home].append(home_stats)
        team_stats_away[away].append(away_stats)
        
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