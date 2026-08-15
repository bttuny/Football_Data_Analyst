# src/ingestion/historical_data.py
import io
import pandas as pd
import requests

class CardsDataFetcher:

    def __init__(self):
        # Palautettu alkuperäinen ja oikea polku: mmz4281
        self.BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league_csv}.csv"

    def fetch_cards_history(self, league_csv: str = "E0") -> pd.DataFrame:
        seasons = ["2324", "2425", "2526", "2627"]
        frames = []
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "text/csv,application/csv,text/html,application/xhtml+xml,*/*",
            "Accept-Language": "en-US,en;q=0.9,fi;q=0.8"
        }

        print(f"⬇️ Aloitetaan lataus liigalle: {league_csv}")
        
        for s in seasons:
            url = self.BASE_URL.format(season=s, league_csv=league_csv)
            try:
                res = requests.get(url, headers=headers, timeout=10)
                
                if res.status_code == 200:
                    content_str = res.content.decode("utf-8", errors="ignore")
                    df = pd.read_csv(io.StringIO(content_str))
                    
                    if "HomeTeam" in df.columns and "HY" in df.columns:
                        df_clean = df.dropna(subset=["HomeTeam", "AwayTeam", "HY", "AY"]).copy()
                        
                        # Turvataan puuttuvat sarakkeet
                        if "HR" not in df_clean.columns: df_clean["HR"] = 0
                        if "AR" not in df_clean.columns: df_clean["AR"] = 0
                        if "Referee" not in df_clean.columns: df_clean["Referee"] = "Unknown"

                        df_clean["home_cards"] = pd.to_numeric(df_clean["HY"], errors="coerce").fillna(0) + \
                                                 (pd.to_numeric(df_clean["HR"], errors="coerce").fillna(0) * 2)
                        df_clean["away_cards"] = pd.to_numeric(df_clean["AY"], errors="coerce").fillna(0) + \
                                                 (pd.to_numeric(df_clean["AR"], errors="coerce").fillna(0) * 2)
                        
                        df_clean["total_cards"] = df_clean["home_cards"] + df_clean["away_cards"]
                        df_clean["Referee"] = df_clean["Referee"].fillna("Unknown").astype(str).str.strip()

                        frames.append(df_clean)
                        print(f"  ✅ Kausi {s}: Ladattu {len(df_clean)} ottelua")
                    else:
                        print(f"  ⚠️ Kausi {s}: Oikeita sarakkeita ei löytynyt!")
                
                elif res.status_code == 404:
                    if s == "2627":
                        print(f"  🔍 Kausi {s}: Ei vielä pelattuja otteluita tällä kaudella.")
                    else:
                        print(f"  ❌ Kausi {s}: Ei löydetty tiedostoa (HTTP 404)")
                else:
                    print(f"  ❌ Kausi {s}: Palvelin esti pyynnön! (HTTP {res.status_code})")
            
            except Exception as e:
                print(f"  ❌ Kausi {s}: Verkkoyhteysvirhe: {e}")

        if frames:
            combined = pd.concat(frames, ignore_index=True)
            print(f"✅ Yhteensä {len(combined)} ottelua tallennettu (CSV: {league_csv})\n")
            return combined
        
        print(f"❌ Ei löydetty dataa (CSV: {league_csv})\n")
        return pd.DataFrame()