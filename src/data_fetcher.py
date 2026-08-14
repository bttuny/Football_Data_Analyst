import requests
import pandas as pd
from typing import Tuple, List, Dict, Any
from config.settings import FOOTBALL_DATA_API_KEY

BASE_URL = "https://api.football-data.org/v4"

class FootballDataFetcher:
    def __init__(self):
        if not FOOTBALL_DATA_API_KEY:
            raise ValueError("FOOTBALL_DATA_API_KEY is not set in the environment variables.")
        self.headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}

    def fetch_premier_league_matches(self, season: int = 2025) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
        """
        Fetches Premier League match data for a given season.
        Returns a DataFrame of matches and a list of teams.
        """
        url = f"{BASE_URL}/competitions/PL/matches?season={season}"
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            raise Exception(f"Failed to fetch data: {response.status_code}: {response.text}")

        data = response.json()
        matches = data.get("matches", [])

        upcoming_raw = [m for m in matches if m.get("status") in ["TIMED", "SCHEDULED"]]
        upcoming_raw.sort(key=lambda x: x.get("utcDate", ""))

        finished_rows = []
        upcoming_matches = []

        for m in upcoming_raw[:10]:
            status = m.get("status")
            home_team = m["homeTeam"]["name"]
            away_team = m["awayTeam"]["name"]
            utc_date = m["utcDate"]

            if status == "FINISHED":
                full_time = m["score"]["fullTime"]
                if full_time["home"] is not None and full_time["away"] is not None:
                    finished_rows.append({
                        "date": utc_date,
                        "home_team": home_team,
                        "away_team": away_team,
                        "home_goals": full_time["home"],
                        "away_goals": full_time["away"],
                    })
            elif status in ["SCHEDULED", "TIMED"]:
                upcoming_matches.append({
                    "api_match_id": m["id"],
                    "home_team": home_team,
                    "away_team": away_team,
                    "datetime": utc_date,
                    "status": "SCHEDULED"
                })
        COLUMNS = ["date", "home_team", "away_team", "home_goals", "away_goals"]
        df_finished = pd.DataFrame(finished_rows, columns=COLUMNS)
        return df_finished, upcoming_matches

                