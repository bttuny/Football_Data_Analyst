# src/cards_data_fetcher.py
import pandas as pd
from typing import Optional

class CardsDataFetcher:
    def __init__(self):
        # Football-Data.co.uk tarjoaa ilmaiset ottelukohtaiset tilastot tuomareineen ja kortteineen
        self.BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/E0.csv"

    def fetch_cards_history(self) -> pd.DataFrame:
        """
        Hakee viimeisimmän kauden ja kuluvan kauden kortti- ja tuomaritilastot.
        """
        seasons = ["2425", "2526"]  # Viime kaudet
        frames = []

        for s in seasons:
            url = self.BASE_URL.format(season=s)
            try:
                df = pd.read_csv(url)
                # Poimitaan vain tarvittavat sarakkeet
                cols = ['Date', 'HomeTeam', 'AwayTeam', 'HY', 'AY', 'HR', 'AR', 'Referee']
                if all(c in df.columns for c in cols):
                    df_clean = df[cols].dropna(subset=['HomeTeam', 'AwayTeam', 'Referee']).copy()
                    
                    # Lasketaan kokonaiskortit (Keltainen = 1, Punainen = 2 korttipistettä)
                    df_clean['home_cards'] = df_clean['HY'] + (df_clean['HR'] * 2)
                    df_clean['away_cards'] = df_clean['AY'] + (df_clean['AR'] * 2)
                    df_clean['total_cards'] = df_clean['home_cards'] + df_clean['away_cards']
                    df_clean['red_cards'] = df_clean['HR'] + df_clean['AR']
                    
                    frames.append(df_clean)
            except Exception as e:
                print(f"Korttidatan lataus epäonnistui kaudelle {s}: {e}")

        if frames:
            return pd.concat(frames, ignore_index=True)
        return pd.DataFrame()