import pandas as pd
import os
import joblib
from datetime import datetime
from sqlalchemy.orm import Session

# Omat tuonnit
from src.core.database import SessionLocal
from src.models.entities import Match
from src.ingestion.odds_fetcher import OddsFetcher

# Yhdistetään tietokannan ID:t Odds API:n lajeihin
LEAGUE_MAP = {
    39: {"name": "EPL", "odds_key": "soccer_epl"},
    140: {"name": "La Liga", "odds_key": "soccer_spain_la_liga"},
    78: {"name": "Bundesliga", "odds_key": "soccer_germany_bundesliga"},
    135: {"name": "Serie A", "odds_key": "soccer_italy_serie_a"},
    61: {"name": "Ligue 1", "odds_key": "soccer_france_ligue_one"}
}

def get_current_team_stats(db: Session, team_name: str, is_home: bool):
    """
    Hakee tietokannasta joukkueen TÄMÄN HETKEN tilastot (viimeiset 10 peliä ja koti/vieras).
    """
    all_matches = db.query(Match).filter(
        (Match.home_team == team_name) | (Match.away_team == team_name),
        Match.status == "FINISHED"
    ).order_by(Match.match_datetime.desc()).limit(10).all()
    
    all_matches = list(reversed(all_matches))
    
    stats_10 = []
    for m in all_matches:
        if m.home_team == team_name:
            stats_10.append({'xg_for': (m.home_xg), 'xg_against': (m.away_xg)})
        else:
            stats_10.append({'xg_for': (m.away_xg), 'xg_against': (m.home_xg)})
            
    if is_home:
        location_matches = db.query(Match).filter(
            Match.home_team == team_name, Match.status == "FINISHED"
        ).order_by(Match.match_datetime.desc()).limit(5).all()
    else:
        location_matches = db.query(Match).filter(
            Match.away_team == team_name, Match.status == "FINISHED"
        ).order_by(Match.match_datetime.desc()).limit(5).all()
        
    location_matches = list(reversed(location_matches))
    
    stats_loc_5 = []
    for m in location_matches:
        if is_home:
            stats_loc_5.append({'xg_for': (m.home_xg), 'xg_against': (m.away_xg)})
        else:
            stats_loc_5.append({'xg_for': (m.away_xg), 'xg_against': (m.home_xg)})

    if len(stats_10) < 10 or len(stats_loc_5) < 5:
        return None

    stats_5 = stats_10[-5:]

    return {
        'xg_avg_5': sum(x['xg_for'] for x in stats_5) / 5,
        'xga_avg_5': sum(x['xg_against'] for x in stats_5) / 5,
        'xg_avg_10': sum(x['xg_for'] for x in stats_10) / 10,
        'xga_avg_10': sum(x['xg_against'] for x in stats_10) / 10,
        'true_loc_xg_5': sum(x['xg_for'] for x in stats_loc_5) / 5,
        'true_loc_xga_5': sum(x['xg_against'] for x in stats_loc_5) / 5,
    }

def run_xgboost_value_finder():
    db = SessionLocal()
    fetcher = OddsFetcher()

    print(f"\n{'='*60}")
    print("🚀 KÄYNNISTETÄÄN XGBOOST YLIKERROIN-MOOTTORI")
    print(f"{'='*60}")

    for league_id, league_info in LEAGUE_MAP.items():
        league_name = league_info["name"]
        odds_key = league_info["odds_key"]

        print(f"\n🔍 Analysoidaan liigaa: {league_name}...")

        # 1. Haetaan tulevat ottelut tietokannasta tälle liigalle
        upcoming_matches = db.query(Match).filter(
            Match.league_id == league_id,
            Match.status != "FINISHED",
            Match.match_datetime >= datetime.utcnow()
        ).all()

        if not upcoming_matches:
            print(f"  -> Ei tulevia otteluita tietokannassa.")
            continue

        # 2. Ladataan oikea XGBoost-malli
        safe_league_name = league_name.lower().replace(" ", "_")
        model_path = f"models/xgb_{safe_league_name}_v1.pkl"
        
        if not os.path.exists(model_path):
            print(f"  -> Varoitus: Mallia ei löydy polusta {model_path}. Ohitetaan.")
            continue
            
        model = joblib.load(model_path)

        # 3. Haetaan kertoimet Odds API:sta tälle liigalle
        events_list = fetcher.fetch_current_odds(sport_key=odds_key)
        if not events_list:
            print(f"  -> Ei kertoimia saatavilla markkinoilta juuri nyt.")
            continue

        # 4. Analysoidaan jokainen tuleva ottelu
        for match in upcoming_matches:
            home = match.home_team
            away = match.away_team
            
            # Yritetään yhdistää kertoimet otteluun fuzzy-matchilla
            prices = fetcher.get_odds_for_match(home, away, events_list)
            
            if prices["H"] == 0.0 or prices["A"] == 0.0:
                continue # Kertoimia ei vielä tarjolla tähän peliin
                
            # Haetaan nykyiset xG-tilastot
            home_stats = get_current_team_stats(db, home, is_home=True)
            away_stats = get_current_team_stats(db, away, is_home=False)
            
            if not home_stats or not away_stats:
                continue # Alkukausi menossa, ei vielä tarpeeksi dataa XGBoostille
                
            # Rakennetaan syöte mallille
            features = pd.DataFrame([{
                'home_xg_avg_5': home_stats['xg_avg_5'],
                'home_xga_avg_5': home_stats['xga_avg_5'],
                'home_xg_avg_10': home_stats['xg_avg_10'],
                'home_xga_avg_10': home_stats['xga_avg_10'],
                'home_true_home_xg_5': home_stats['true_loc_xg_5'],
                'home_true_home_xga_5': home_stats['true_loc_xga_5'],
                
                'away_xg_avg_5': away_stats['xg_avg_5'],
                'away_xga_avg_5': away_stats['xga_avg_5'],
                'away_xg_avg_10': away_stats['xg_avg_10'],
                'away_xga_avg_10': away_stats['xga_avg_10'],
                'away_true_away_xg_5': away_stats['true_loc_xg_5'],
                'away_true_away_xga_5': away_stats['true_loc_xga_5'],
            }])
            
            # Ennustetaan todennäköisyydet: 0=Vieras, 1=Tasan, 2=Koti
            probs = model.predict_proba(features)[0]
            prob_away, prob_draw, prob_home = probs[0], probs[1], probs[2]
            
            # Lasketaan Expected Value (EV) prosentteina
            ev_1 = (prob_home * prices["H"]) - 1
            ev_x = (prob_draw * prices["D"]) - 1
            ev_2 = (prob_away * prices["A"]) - 1
            
            # Oletus: Jos tuotto-odotus on yli 5% (0.05), se on pelattava kohde
            if any(ev > 0.05 for ev in [ev_1, ev_x, ev_2]):
                print(f"\n🔥 {home} vs {away}")
                print(f"   📊 Ennuste  : 1: {prob_home*100:.1f}% | X: {prob_draw*100:.1f}% | 2: {prob_away*100:.1f}%")
                print(f"   💰 Kertoimet: 1: {prices['H']:.2f}  | X: {prices['D']:.2f}  | 2: {prices['A']:.2f}")
                
                if ev_1 > 0.05:
                    print(f"   👉 PELIVALINTA: 1 (Kotivoitto) | EV: +{ev_1*100:.1f}%")
                if ev_x > 0.05:
                    print(f"   👉 PELIVALINTA: X (Tasapeli)   | EV: +{ev_x*100:.1f}%")
                if ev_2 > 0.05:
                    print(f"   👉 PELIVALINTA: 2 (Vierasvoitto)| EV: +{ev_2*100:.1f}%")

    db.close()
    print(f"\n{'='*60}")
    print("✅ Analyysi valmis!")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    run_xgboost_value_finder()