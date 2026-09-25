import pandas as pd
import requests
import time
import os
from io import StringIO
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime

# Omat tuonnit
from src.core.database import SessionLocal
from src.models.entities import Match
from src.ingestion.odds_fetcher import clean_team_name

CLUB_ELO_ALIASES = {
    "manchester united": "ManUnited",
    "manchester city": "ManCity",
    "tottenham": "Spurs",
    "newcastle": "Newcastle",
    "nottingham forest": "Forest",
    "aston villa": "AstonVilla",
    "crystal palace": "CrystalPalace",
    "west ham": "WestHam",
    "bayern munich": "Bayern",
    "borussia dortmund": "Dortmund",
    "bayer leverkusen": "Leverkusen",
    "rb leipzig": "RBLeipzig",
    "monchengladbach": "Gladbach",
    "cologne": "Koeln",
    "stuttgart": "Stuttgart",
    "eintracht frankfurt": "Frankfurt",
    "real madrid": "RealMadrid",
    "atletico madrid": "Atletico",
    "athletic bilbao": "Athletic",
    "real sociedad": "Sociedad",
    "real betis": "Betis",
    "celta vigo": "Celta",
    "deportivo la coruna": "Deportivo",
    "racing santander": "Racing",
    "valladolid": "Valladolid",
    "inter milan": "Inter",
    "ac milan": "Milan",
    "as roma": "Roma",
    "paris saint germain": "PSG",
    "le havre": "LeHavre",
    "paris fc": "ParisFC",
    "hamburger sv": "Hamburg",
    "werder bremen": "Werder",
    "union berlin": "UnionBerlin"
}

MASTER_CSV_PATH = "data/clubelo_master.csv"

def get_clubelo_name(team_name: str) -> str:
    clean_name = clean_team_name(team_name)
    if clean_name in CLUB_ELO_ALIASES:
        return CLUB_ELO_ALIASES[clean_name]
    return "".join(word.capitalize() for word in clean_name.split())

def ensure_elo_columns_exist(db: Session):
    try:
        db.execute(text("ALTER TABLE matches ADD COLUMN home_elo FLOAT"))
        db.execute(text("ALTER TABLE matches ADD COLUMN away_elo FLOAT"))
        db.commit()
    except Exception:
        db.rollback() 

def update_elo_ratings():
    db = SessionLocal()
    ensure_elo_columns_exist(db)

    # Etsitään ottelut, joilta puuttuu Elo
    matches_to_update = db.query(Match).filter(
        (Match.home_elo.is_(None)) | (Match.away_elo.is_(None))
    ).all()

    if not matches_to_update:
        print("Kaikilla otteluilla on jo Elo-luvut!")
        db.close()
        return
        
    print(f"Päivitetään Elo-luvut {len(matches_to_update)} ottelulle...")
    
    # 1. Ladataan tai luodaan Master CSV
    if os.path.exists(MASTER_CSV_PATH):
        print("Ladataan paikallinen clubelo_master.csv välimuisti...")
        master_df = pd.read_csv(MASTER_CSV_PATH)
        master_df['From'] = pd.to_datetime(master_df['From'])
        master_df['To'] = pd.to_datetime(master_df['To'])
    else:
        print("Luodaan uusi clubelo_master.csv...")
        master_df = pd.DataFrame(columns=['Club', 'Elo', 'From', 'To', 'QueryName'])

    # 2. Selvitetään puuttuvat joukkueet
    needed_teams = set()
    for m in matches_to_update:
        needed_teams.add(get_clubelo_name(m.home_team))
        needed_teams.add(get_clubelo_name(m.away_team))

    existing_teams = set(master_df['QueryName'].unique()) if not master_df.empty else set()
    missing_teams = needed_teams - existing_teams

    # 3. Haetaan puuttuvat netistä (Pysähtyy nätisti jos tulee 502)
    if missing_teams:
        print(f"Löydettiin {len(missing_teams)} puuttuvaa joukkuetta. Haetaan API:sta...")
        os.makedirs(os.path.dirname(MASTER_CSV_PATH) or ".", exist_ok=True)
        headers = {"User-Agent": "Mozilla/5.0"}
        new_dfs = []
        
        for club in missing_teams:
            url = f"http://api.clubelo.com/{club}"
            try:
                res = requests.get(url, headers=headers, timeout=10)
                if res.status_code == 200 and "Elo" in res.text:
                    df = pd.read_csv(StringIO(res.text))
                    if not df.empty and 'Elo' in df.columns:
                        df['From'] = pd.to_datetime(df['From'])
                        df['To'] = pd.to_datetime(df['To'])
                        df['QueryName'] = club
                        new_dfs.append(df)
                        print(f"✅ Ladattu: {club}")
                elif res.status_code in [502, 503, 504]:
                    print(f"\n❌ 502 Virhe. ClubElo on alhaalla. Keskeytetään verkkohaku, jatketaan jo tallennetuilla.")
                    break # Lopettaa haun, mutta koodi jatkaa suoritusta!
                else:
                    print(f"⚠️ Ei löydetty: {club} (HTTP {res.status_code})")
            except Exception as e:
                print(f"Virhe haussa {club}: {e}")
                break
            
            time.sleep(2) # Kunnioitetaan palvelinta
            
        if new_dfs:
            master_df = pd.concat([master_df] + new_dfs, ignore_index=True)
            master_df.to_csv(MASTER_CSV_PATH, index=False)
            print("💾 Uudet joukkueet tallennettu CSV:hen!")

    # 4. Päivitetään tietokanta
    print("Viedään lukuja tietokantaan...")
    updated_count = 0
    for match in matches_to_update:
        match_date = pd.to_datetime(match.match_datetime.strftime("%Y-%m-%d"))
        
        for team, is_home in [(match.home_team, True), (match.away_team, False)]:
            club_name = get_clubelo_name(team)
            club_data = master_df[master_df['QueryName'] == club_name]
            
            if not club_data.empty:
                mask = (club_data['From'] <= match_date) & (club_data['To'] >= match_date)
                matching_rows = club_data.loc[mask]
                
                if not matching_rows.empty:
                    elo_val = float(matching_rows.iloc[0]['Elo'])
                else:
                    # Jos pelipäivä on tulevaisuudessa, otetaan joukkueen tuorein luku
                    elo_val = float(club_data.iloc[-1]['Elo'])
                    
                if is_home:
                    match.home_elo = elo_val
                else:
                    match.away_elo = elo_val
                updated_count += 1

    db.commit()
    db.close()
    print(f"✅ Valmis! Yritettiin päivittää {updated_count} lukua kantaan.")

if __name__ == "__main__":
    update_elo_ratings()