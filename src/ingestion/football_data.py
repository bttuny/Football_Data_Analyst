import os
import requests
import pandas as pd

class FootballDataFetcher:

    def __init__(self):
        self.api_key = os.getenv("FOOTBALL_DATA_API_KEY")
        self.base_url = "https://api.football-data.org/v4"
        self.headers = (
            {"X-Auth-Token": self.api_key} if self.api_key else {}
        )

    def fetch_matches(
        self, competition_code: str = "PL", season: int = 2026
    ) -> tuple[pd.DataFrame, list]:
        if not self.api_key:
            print("WARNING: FOOTBALL_DATA_API_KEY puuttuu.")
            return (
                pd.DataFrame(
                    columns=[
                        "date",
                        "home_team",
                        "away_team",
                        "home_goals",
                        "away_goals",
                    ]
                ),
                [],
            )

        url = f"{self.base_url}/competitions/{competition_code}/matches"
        res = requests.get(
            url, headers=self.headers, params={"season": season}
        )
        if res.status_code != 200:
            return (
                pd.DataFrame(
                    columns=[
                        "date",
                        "home_team",
                        "away_team",
                        "home_goals",
                        "away_goals",
                    ]
                ),
                [],
            )

        matches = res.json().get("matches", [])
        finished, upcoming_raw = [], []
        
        

        for m in matches:
            if m.get("status") == "FINISHED":
                ft = m["score"]["fullTime"]
                if ft["home"] is not None and ft["away"] is not None:
                    finished.append({
                        "date": m["utcDate"],
                        "home_team": m["homeTeam"]["name"],
                        "away_team": m["awayTeam"]["name"],
                        "home_goals": int(ft["home"]),
                        "away_goals": int(ft["away"]),
                    })
            elif m.get("status") in ["TIMED", "SCHEDULED"]:
                referees_list = m.get("referees", [])
                main_ref = referees_list[0].get("name") if referees_list else None
                upcoming_raw.append({
                    "datetime": m["utcDate"],
                    "home_team": m["homeTeam"]["name"],
                    "away_team": m["awayTeam"]["name"],
                    "matchday": m.get("matchday"),
                    "referee": main_ref
                })

        upcoming_raw.sort(key=lambda x: x.get("datetime", ""))
        df_fin = pd.DataFrame(
            finished,
            columns=[
                "date",
                "home_team",
                "away_team",
                "home_goals",
                "away_goals",
            ],
        )
        return df_fin, upcoming_raw[:10]  # Seuraavat 10 peliä