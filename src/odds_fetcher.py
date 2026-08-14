# src/odds_fetcher.py
import requests
import os
import re
from typing import Dict, Any

def clean_team_name(name: str) -> str:
    """
    Puhdistaa joukkueen nimestä FC, AFC ja ylimääräiset välilyönnit vertailua varten.
    Esim: 'Arsenal FC' -> 'arsenal', 'Hull City AFC' -> 'hull city'
    """
    cleaned = re.sub(r'\b(FC|AFC)\b', '', name, flags=re.IGNORECASE)
    return " ".join(cleaned.lower().split())

class OddsFetcher:
    def __init__(self):
        self.api_key = os.getenv("ODDS_API_KEY")

    def fetch_current_odds(self) -> Dict[str, Dict[str, float]]:
        if not self.api_key:
            print(">>> VIRHE: ODDS_API_KEY puuttuu ympäristömuuttujista!")
            return {}

        url = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "eu",
            "markets": "h2h",
            "oddsFormat": "decimal"
        }

        response = requests.get(url, params=params)
        if response.status_code != 200:
            return {}

        data = response.json()
        odds_dict = {}

        for match in data:
            home_team = match["home_team"]
            away_team = match["away_team"]
            
            if match.get("bookmakers"):
                bookie = match["bookmakers"][0]
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

                    # Tallennetaan puhdistetulla avaimella
                    clean_key = f"{clean_team_name(home_team)} vs {clean_team_name(away_team)}"
                    odds_dict[clean_key] = {"H": h_odds, "D": d_odds, "A": a_odds}

        return odds_dict