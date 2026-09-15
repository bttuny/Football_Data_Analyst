import asyncio
import aiohttp
from understat import Understat
from sqlalchemy.orm import Session
from datetime import datetime

# Omat tuonnit
from src.core.database import SessionLocal
from src.models.entities import Match
from src.ingestion.odds_fetcher import clean_team_name

# TÄRKEÄÄ: Päivitä nämä vastaamaan Supabasen leagues-taulusi ID:itä!
LEAGUE_ID_MAPPING = {
    "epl": 2,          # Valioliiga
    "la_liga": 3,     # La Liga
    "bundesliga": 4,   # Bundesliga
    "serie_a": 5,     # Serie A
    "ligue_1": 6       # Ligue 1
}

async def fetch_and_save_xg(league="epl", season=2021):
    print(f"Käsitellään {league.upper()} kauden {season} dataa...")
    
    league_id = LEAGUE_ID_MAPPING.get(league)
    if not league_id:
        print(f"Virhe: Liigalle '{league}' ei löydy ID:tä kartoituksesta!")
        return

    async with aiohttp.ClientSession() as session:
        understat = Understat(session)
        matches = await understat.get_league_results(league, season)
        
        if not matches:
            print(f"Dataa ei löytynyt liigalle {league} kaudella {season}!")
            return

        db: Session = SessionLocal()
        updated_count = 0
        created_count = 0

        # Haemme kerralla kaikki tämän kauden ottelut tietokannasta välimuistiin
        db_matches = db.query(Match).filter(Match.season == str(season)).all()

        for match_data in matches:
            if not match_data.get("isResult"):
                continue # Ohitetaan pelaamattomat ottelut

            # Siivotaan Understatin antamat nimet vertailua varten
            u_home_clean = clean_team_name(match_data["h"]["title"])
            u_away_clean = clean_team_name(match_data["a"]["title"])
            
            home_xg = float(match_data["xG"]["h"])
            away_xg = float(match_data["xG"]["a"])
            actual_home_goals = int(match_data["goals"]["h"])
            actual_away_goals = int(match_data["goals"]["a"])
            
            # Parsitaan päivämäärä oikeaan muotoon
            # Esim. "2021-08-13 19:00:00"
            dt_obj = datetime.strptime(match_data["datetime"], "%Y-%m-%d %H:%M:%S")
            
            # Etsitään välimuistissa olevista tietokannan otteluista oikea
            db_match = None
            for m in db_matches:
                db_home_clean = clean_team_name(m.home_team)
                db_away_clean = clean_team_name(m.away_team)
                
                if db_home_clean == u_home_clean and db_away_clean == u_away_clean:
                    db_match = m
                    break

            if db_match:
                # OTTELU LÖYTYY: Päivitetään xG:t ja maalit (varmuuden vuoksi)
                db_match.home_xg = home_xg
                db_match.away_xg = away_xg
                db_match.actual_home_goals = actual_home_goals
                db_match.actual_away_goals = actual_away_goals
                db_match.status = "FINISHED"
                updated_count += 1
            else:
                # OTTELUA EI LÖYDY: Luodaan uusi historiallinen ottelu!
                new_match = Match(
                    league_id=league_id,
                    season=str(season),
                    home_team=match_data["h"]["title"], # Käytetään Understatin kaunista nimeä
                    away_team=match_data["a"]["title"],
                    match_datetime=dt_obj,
                    status="FINISHED",
                    actual_home_goals=actual_home_goals,
                    actual_away_goals=actual_away_goals,
                    home_xg=home_xg,
                    away_xg=away_xg
                )
                db.add(new_match)
                created_count += 1

        db.commit()
        db.close()
        print(f"Valmis! Päivitettiin {updated_count} ja LUOTIIN {created_count} uutta ottelua liigassa {league}!")

if __name__ == "__main__":
    async def main():
        liigat = ["epl", "la_liga", "bundesliga", "serie_a", "ligue_1"]
        kaudet = [2021, 2022, 2023, 2024, 2025]
        
        for liiga in liigat:
            for kausi in kaudet:
                await fetch_and_save_xg(liiga, kausi)
                await asyncio.sleep(2) # Kunnioitetaan Understatin palvelimia
            
    asyncio.run(main())