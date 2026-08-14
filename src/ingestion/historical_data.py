# src/ingestion/historical_data.py
import io
import pandas as pd
import requests


class CardsDataFetcher:

    def __init__(self):
        self.BASE_URL = (
            "https://www.football-data.co.uk/mmz4281/{season}/{league_csv}.csv"
        )

    def fetch_cards_history(self, league_csv: str = "E0") -> pd.DataFrame:
        seasons = ["2324", "2425", "2526", "2627"]
        frames = []
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

        for s in seasons:
            url = self.BASE_URL.format(season=s, league_csv=league_csv)
            try:
                res = requests.get(url, headers=headers, timeout=10)
                if res.status_code == 200:
                    df = pd.read_csv(
                        io.StringIO(
                            res.content.decode("utf-8", errors="ignore")
                        )
                    )
                    cols = [
                        "Date",
                        "HomeTeam",
                        "AwayTeam",
                        "HY",
                        "AY",
                        "HR",
                        "AR",
                        "Referee",
                    ]
                    if all(c in df.columns for c in cols):
                        df_clean = df[cols].dropna(
                            subset=["HomeTeam", "AwayTeam", "Referee", "HY", "AY"]
                        ).copy()

                        df_clean["home_cards"] = pd.to_numeric(
                            df_clean["HY"], errors="coerce"
                        ).fillna(0) + (
                            pd.to_numeric(
                                df_clean["HR"], errors="coerce"
                            ).fillna(0)
                            * 2
                        )
                        df_clean["away_cards"] = pd.to_numeric(
                            df_clean["AY"], errors="coerce"
                        ).fillna(0) + (
                            pd.to_numeric(
                                df_clean["AR"], errors="coerce"
                            ).fillna(0)
                            * 2
                        )
                        df_clean["total_cards"] = (
                            df_clean["home_cards"] + df_clean["away_cards"]
                        )
                        df_clean["red_cards"] = pd.to_numeric(
                            df_clean["HR"], errors="coerce"
                        ).fillna(0) + pd.to_numeric(
                            df_clean["AR"], errors="coerce"
                        ).fillna(0)
                        df_clean["Referee"] = (
                            df_clean["Referee"].astype(str).str.strip()
                        )

                        if not df_clean.empty:
                            frames.append(df_clean)
            except Exception:
                pass

        return (
            pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        )