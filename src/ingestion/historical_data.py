# src/ingestion/historical_data.py
import pandas as pd
import requests
import io

class CardsDataFetcher:
    def __init__(self):
        # Football-Data.co.uk kausikohtaiset CSV-arkistot (E0 = English Premier League)
        self.BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/E0.csv"

    def fetch_cards_history(self) -> pd.DataFrame:
        """
        Lataa menneiden Valioliiga-kausien toteutuneet kortti- ja tuomaritilastot.
        Kaudet: 2324, 2425, 2526
        """
        seasons = ["2324", "2425", "2526", "2627"]
        frames = []

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }

        for s in seasons:
            url = self.BASE_URL.format(season=s)
            try:
                res = requests.get(url, headers=headers, timeout=10)
                if res.status_code == 200:
                    df = pd.read_csv(io.StringIO(res.content.decode('utf-8', errors='ignore')))
                    
                    cols = ['Date', 'HomeTeam', 'AwayTeam', 'HY', 'AY', 'HR', 'AR', 'Referee']
                    if all(c in df.columns for c in cols):
                        df_clean = df[cols].dropna(subset=['HomeTeam', 'AwayTeam', 'Referee', 'HY', 'AY']).copy()
                        
                        # Keltainen = 1 korttipiste, Punainen = 2 korttipistettä
                        df_clean['home_cards'] = pd.to_numeric(df_clean['HY'], errors='coerce').fillna(0) + (pd.to_numeric(df_clean['HR'], errors='coerce').fillna(0) * 2)
                        df_clean['away_cards'] = pd.to_numeric(df_clean['AY'], errors='coerce').fillna(0) + (pd.to_numeric(df_clean['AR'], errors='coerce').fillna(0) * 2)
                        df_clean['total_cards'] = df_clean['home_cards'] + df_clean['away_cards']
                        df_clean['red_cards'] = pd.to_numeric(df_clean['HR'], errors='coerce').fillna(0) + pd.to_numeric(df_clean['AR'], errors='coerce').fillna(0)
                        
                        # Siistitään tuomarin nimi (esim. 'A Taylor' tai 'Anthony Taylor')
                        df_clean['Referee'] = df_clean['Referee'].astype(str).str.strip()
                        
                        frames.append(df_clean)
                        print(f"   -> Ladattu {len(df_clean)} ottelua tuomari- ja korttidataa kaudelta {s}")
            except Exception as e:
                print(f"Korttidatan lataus epäonnistui kaudelle {s}: {e}")

        if frames:
            total_df = pd.concat(frames, ignore_index=True)
            print(f"Yhteensä ladattu {len(total_df)} historiallista ottelua korttianalyysiin.")
            return total_df

        return pd.DataFrame()