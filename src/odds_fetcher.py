import requests
import os
from typing import Dict, Any

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"

class OddsFetcher:
    def __init__(self):
        self.api_key = ODDS_API_KEY

    def fetch_current_odds(self) -> Dict[str, Dict[str, float]]:
        """
        Gets Premier League 1x2-odds and return those in a form
        { "Arsenal FC vs Coventry City FC": {"H": 1.35, "D": 5.50, "A": 9.00} }
        """
        if not self.api_key:
            print("WARNING: ODDS_API_KEY missing.")
            return {}

        params = {
            "apiKey": self.api_key,
            "regions": "eu",
            "markets": "h2h",
            "oddsFormat": "decimal"
        }

        response = requests.get(BASE_URL, params=params)
        if response.status_code != 200:
            print(f"Odds API Error: {response.status_code}")
            return {}

        data = response.json()
        odds_dict = {}

        for match in data:
            home_team = match["home_team"]
            away_team = match["away_team"]

            if match.get("bookmakers"):
                bookie = next((b for b in match["bookmakers"] if b["key"] == "coolbet"), None)

                if bookie:
                    h2h_market = next((m for m in bookie["markets"] if m["key"] == "h2h"), None)

                    if h2h_market:
                        h_odds, d_odds, a_odds = 1.0, 1.0, 1.0
                        for outcome in h2h_market["outcomes"]:
                            if outcome["name"] == home_team:
                                h_odds = outcome["price"]
                            elif outcome["name"] == away_team:
                                a_odds = outcome["price"]
                            elif outcome["name"] == "Draw":
                                d_odds = outcome["price"]

                        key = f"{home_team} vs {away_team}"
                        odds_dict[key] = {"H": h_odds, "D": d_odds, "A": a_odds}

        return odds_dict