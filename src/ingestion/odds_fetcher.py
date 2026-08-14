import os
import re
import requests
from typing import Dict


def clean_team_name(name: str) -> str:
    cleaned = re.sub(r"\b(FC|AFC)\b", "", name, flags=re.IGNORECASE)
    return " ".join(cleaned.lower().split())


class OddsFetcher:

    def __init__(self):
        self.api_key = os.getenv("ODDS_API_KEY")

    def fetch_current_odds(
        self, sport_key: str = "soccer_epl"
    ) -> Dict[str, Dict[str, float]]:
        if not self.api_key:
            return {}

        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "eu",
            "markets": "h2h",
            "oddsFormat": "decimal",
        }
        res = requests.get(url, params=params)
        if res.status_code != 200:
            return {}

        data = res.json()
        odds_dict = {}
        for match in data:
            if match.get("bookmakers"):
                bookie = match["bookmakers"][0]
                h2h = next(
                    (m for m in bookie["markets"] if m["key"] == "h2h"), None
                )
                if h2h:
                    h, d, a = 1.0, 1.0, 1.0
                    for out in h2h["outcomes"]:
                        if out["name"] == match["home_team"]:
                            h = out["price"]
                        elif out["name"] == match["away_team"]:
                            a = out["price"]
                        elif out["name"] == "Draw":
                            d = out["price"]
                    key = f"{clean_team_name(match['home_team'])} vs {clean_team_name(match['away_team'])}"
                    odds_dict[key] = {"H": h, "D": d, "A": a}
        return odds_dict