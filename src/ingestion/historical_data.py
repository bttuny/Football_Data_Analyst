import pandas as pd


class CardsDataFetcher:

    def __init__(self):
        self.BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/E0.csv"

    def fetch_cards_history(self) -> pd.DataFrame:
        frames = []
        for s in ["2425", "2526"]:
            try:
                df = pd.read_csv(self.BASE_URL.format(season=s))
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
                    c_df = df[cols].dropna(
                        subset=["HomeTeam", "AwayTeam", "Referee"]
                    ).copy()
                    c_df["home_cards"] = c_df["HY"] + (c_df["HR"] * 2)
                    c_df["away_cards"] = c_df["AY"] + (c_df["AR"] * 2)
                    c_df["total_cards"] = (
                        c_df["home_cards"] + c_df["away_cards"]
                    )
                    c_df["red_cards"] = c_df["HR"] + c_df["AR"]
                    frames.append(c_df)
            except Exception:
                pass
        return (
            pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        )