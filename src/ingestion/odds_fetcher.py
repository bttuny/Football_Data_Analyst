# src/ingestion/odds_fetcher.py
import difflib
import os
import re
import unicodedata
from typing import Any, Dict
import requests

TEAM_ALIASES = {
    # Espanja
    "alaves": "alaves",
    "deportivo alaves": "alaves",
    "getafe": "getafe",
    "getafe cf": "getafe",
    "sevilla": "sevilla",
    "sevilla fc": "sevilla",
    "rayo vallecano": "rayo vallecano",
    "rayo vallecano de madrid": "rayo vallecano",
    "racing santander": "racing santander",
    "real racing club de santander": "racing santander",
    "racing de santander": "racing santander",
    "villarreal": "villarreal",
    "villarreal cf": "villarreal",
    "espanyol": "espanyol",
    "rcd espanyol": "espanyol",
    "rcd espanyol de barcelona": "espanyol",
    "levante": "levante",
    "levante ud": "levante",
    "deportivo la coruna": "deportivo la coruna",
    "rc deportivo la coruna": "deportivo la coruna",
    "elche": "elche",
    "elche cf": "elche",
    "atletico madrid": "atletico madrid",
    "club atletico de madrid": "atletico madrid",
    "malaga": "malaga",
    "malaga cf": "malaga",
    "real betis": "real betis",
    "real betis balompie": "real betis",
    "real sociedad": "real sociedad",
    "real sociedad de futbol": "real sociedad",
    "athletic club": "athletic bilbao",
    "athletic club bilbao": "athletic bilbao",
    "valencia": "valencia",
    "valencia cf": "valencia",
    "celta vigo": "celta vigo",
    "rc celta de vigo": "celta vigo",
    "celta de vigo": "celta vigo",
    "osasuna": "osasuna",
    "ca osasuna": "osasuna",
    "mallorca": "mallorca",
    "rcd mallorca": "mallorca",
    "girona": "girona",
    "girona fc": "girona",
    "leganes": "leganes",
    "cd leganes": "leganes",
    "valladolid": "valladolid",
    "real valladolid cf": "valladolid",
    # Englanti
    "brighton": "brighton",
    "brighton and hove albion": "brighton",
    "brighton & hove albion fc": "brighton",
    "aston villa": "aston villa",
    "aston villa fc": "aston villa",
    "arsenal": "arsenal",
    "arsenal fc": "arsenal",
    "coventry": "coventry",
    "coventry city fc": "coventry",
    "hull city": "hull",
    "hull city afc": "hull",
    "manchester united": "manchester united",
    "manchester united fc": "manchester united",
    "everton": "everton",
    "everton fc": "everton",
    "crystal palace": "crystal palace",
    "crystal palace fc": "crystal palace",
    "nottingham forest": "nottingham forest",
    "nottingham forest fc": "nottingham forest",
    "leeds united": "leeds",
    "leeds united fc": "leeds",
    "ipswich town": "ipswich",
    "ipswich town fc": "ipswich",
    "sunderland": "sunderland",
    "sunderland afc": "sunderland",
    "brentford": "brentford",
    "brentford fc": "brentford",
    "tottenham hotspur": "tottenham",
    "tottenham hotspur fc": "tottenham",
    "manchester city": "manchester city",
    "manchester city fc": "manchester city",
    "bournemouth": "bournemouth",
    "afc bournemouth": "bournemouth",
    "newcastle united": "newcastle",
    "newcastle united fc": "newcastle",
    "liverpool": "liverpool",
    "liverpool fc": "liverpool",
    "chelsea": "chelsea",
    "chelsea fc": "chelsea",
    "fulham": "fulham",
    "fulham fc": "fulham",
    # Saksa
    "bayern munich": "bayern munich",
    "fc bayern munchen": "bayern munich",
    "bayern munchen": "bayern munich",
    "stuttgart": "stuttgart",
    "vfb stuttgart": "stuttgart",
    "elversberg": "elversberg",
    "sv 07 elversberg": "elversberg",
    "sv elversberg": "elversberg",
    "bayer leverkusen": "bayer leverkusen",
    "bayer 04 leverkusen": "bayer leverkusen",
    "koln": "cologne",
    "cologne": "cologne",
    "1. fc koln": "cologne",
    "fc koln": "cologne",
    "hoffenheim": "hoffenheim",
    "tsg 1899 hoffenheim": "hoffenheim",
    "tsg hoffenheim": "hoffenheim",
    "union berlin": "union berlin",
    "1. fc union berlin": "union berlin",
    "frankfurt": "eintracht frankfurt",
    "eintracht frankfurt": "eintracht frankfurt",
    "mainz": "mainz",
    "1. fsv mainz 05": "mainz",
    "fsv mainz 05": "mainz",
    "paderborn": "paderborn",
    "sc paderborn 07": "paderborn",
    "rb leipzig": "rb leipzig",
    "rasenballsport leipzig": "rb leipzig",
    "borussia monchengladbach": "monchengladbach",
    "monchengladbach": "monchengladbach",
    "dortmund": "borussia dortmund",
    "borussia dortmund": "borussia dortmund",
    "hamburger sv": "hamburg",
    "hamburg": "hamburg",
    "freiburg": "freiburg",
    "sc freiburg": "freiburg",
    "werder bremen": "werder bremen",
    "sv werder bremen": "werder bremen",
    "augsburg": "augsburg",
    "fc augsburg": "augsburg",
    "schalke": "schalke",
    "schalke 04": "schalke",
    "fc schalke 04": "schalke",
    # Ranska
    "marseille": "marseille",
    "olympique de marseille": "marseille",
    "strasbourg": "strasbourg",
    "rc strasbourg alsace": "strasbourg",
    "rc strasbourg": "strasbourg",
    "lens": "lens",
    "rc lens": "lens",
    "racing club de lens": "lens",
    "auxerre": "auxerre",
    "aj auxerre": "auxerre",
    "toulouse": "toulouse",
    "toulouse fc": "toulouse",
    "lyon": "lyon",
    "olympique lyonnais": "lyon",
    "nice": "nice",
    "ogc nice": "nice",
    "lorient": "lorient",
    "fc lorient": "lorient",
    "troyes": "troyes",
    "es troyes ac": "troyes",
    "paris fc": "paris fc",
    "le mans": "le mans",
    "le mans fc": "le mans",
    "brest": "brest",
    "stade brestois 29": "brest",
    "stade brestois": "brest",
    "angers": "angers",
    "angers sco": "angers",
    "lille": "lille",
    "lille osc": "lille",
    "le havre": "le havre",
    "le havre ac": "le havre",
    "monaco": "monaco",
    "as monaco fc": "monaco",
    "as monaco": "monaco",
    "psg": "paris saint germain",
    "paris sg": "paris saint germain",
    "paris saint-germain": "paris saint germain",
    "paris saint germain": "paris saint germain",
    "paris saint-germain fc": "paris saint germain",
    "rennes": "rennes",
    "stade rennais fc 1901": "rennes",
    "stade rennais fc": "rennes",
    "stade rennais": "rennes",
    # Italia
    "inter": "inter milan",
    "inter milan": "inter milan",
    "fc internazionale milano": "inter milan",
    "monza": "monza",
    "ac monza": "monza",
    "udinese": "udinese",
    "udinese calcio": "udinese",
    "como": "como",
    "como 1907": "como",
    "genoa": "genoa",
    "genoa cfc": "genoa",
    "napoli": "napoli",
    "ssc napoli": "napoli",
    "parma": "parma",
    "parma calcio 1913": "parma",
    "cagliari": "cagliari",
    "cagliari calcio": "cagliari",
    "venezia": "venezia",
    "venezia fc": "venezia",
    "lecce": "lecce",
    "us lecce": "lecce",
    "frosinone": "frosinone",
    "frosinone calcio": "frosinone",
    "juventus": "juventus",
    "juventus fc": "juventus",
    "atalanta": "atalanta",
    "atalanta bc": "atalanta",
    "sassuolo": "sassuolo",
    "us sassuolo calcio": "sassuolo",
    "torino": "torino",
    "torino fc": "torino",
    "milan": "ac milan",
    "ac milan": "ac milan",
    "bologna": "bologna",
    "bologna fc 1909": "bologna",
    "lazio": "lazio",
    "ss lazio": "lazio",
    "roma": "as roma",
    "as roma": "as roma",
    "fiorentina": "fiorentina",
    "acf fiorentina": "fiorentina",
}


def clean_team_name(name: str) -> str:
    if not name:
        return ""
    # Poistetaan aksentit ja ääkköset: ä->a, é->e, ü->u jne.
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c)).lower().strip()

    # Poistetaan erikoismerkit
    n = re.sub(r"[\.\,\-\']", " ", n)
    n = re.sub(r"\s+", " ", n).strip()

    if n in TEAM_ALIASES:
        return TEAM_ALIASES[n]

    # Poistetaan yleiset etuliitteet/loppuliitteet
    noise = [
        "fc",
        "afc",
        "cf",
        "sc",
        "rcd",
        "rc",
        "ca",
        "cd",
        "ac",
        "as",
        "ss",
        "ssc",
        "us",
        "vfl",
        "vfb",
        "sv",
        "tsg",
        "1.",
        "bsc",
        "hsc",
        "osc",
        "ogc",
        "de",
        "1909",
        "1846",
        "1848",
        "1910",
        "1913",
        "1907",
        "04",
        "05",
        "07",
        "29",
    ]
    for w in noise:
        n = re.sub(rf"\b{w}\b", "", n).strip()

    n = re.sub(r"\s+", " ", n).strip()
    return TEAM_ALIASES.get(n, n)


def match_similarity(n1: str, n2: str) -> float:
    """Laskee samankaltaisuuden kahden nimen välillä (0.0 - 1.0)."""
    c1, c2 = clean_team_name(n1), clean_team_name(n2)
    if c1 == c2:
        return 1.0
    if c1 in c2 or c2 in c1:
        return 0.9
    return difflib.SequenceMatcher(None, c1, c2).ratio()


class OddsFetcher:

    def __init__(self):
        self.api_key = os.getenv("ODDS_API_KEY")
        self.base_url = "https://api.the-odds-api.com/v4/sports"

    def fetch_current_odds(
        self, sport_key: str = "soccer_epl"
    ) -> list:
        if not self.api_key:
            return []

        url = f"{self.base_url}/{sport_key}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "eu",
            "markets": "h2h",
            "oddsFormat": "decimal",
        }

        try:
            res = requests.get(url, params=params, timeout=10)
            if res.status_code != 200:
                return []

            data = res.json()
            events_list = []

            for event in data:
                h_raw = event.get("home_team", "")
                a_raw = event.get("away_team", "")
                h_clean = clean_team_name(h_raw)
                a_clean = clean_team_name(a_raw)

                prices = {"H": 0.0, "D": 0.0, "A": 0.0}
                for bm in event.get("bookmakers", []):
                    for m in bm.get("markets", []):
                        if m.get("key") == "h2h":
                            for oc in m.get("outcomes", []):
                                oc_name = oc.get("name", "")
                                if (
                                    clean_team_name(oc_name) == h_clean
                                    or oc_name == h_raw
                                ):
                                    prices["H"] = float(oc.get("price", 0.0))
                                elif (
                                    clean_team_name(oc_name) == a_clean
                                    or oc_name == a_raw
                                ):
                                    prices["A"] = float(oc.get("price", 0.0))
                                elif "draw" in oc_name.lower():
                                    prices["D"] = float(oc.get("price", 0.0))
                            if prices["H"] > 0 and prices["A"] > 0:
                                break
                    if prices["H"] > 0 and prices["A"] > 0:
                        break

                if prices["H"] > 0:
                    events_list.append({
                        "home_clean": h_clean,
                        "away_clean": a_clean,
                        "prices": prices,
                    })

            return events_list
        except Exception:
            return []

    def get_odds_for_match(
        self,
        home_name: str,
        away_name: str,
        events_list: list,
        sport_key: str = "soccer_epl",
    ) -> Dict[str, float]:
        """Etsii kertoimet ottelulle parhaalla fuzzy-osumalla."""
        h_clean = clean_team_name(home_name)
        a_clean = clean_team_name(away_name)

        best_score = 0.0
        best_prices = {"H": 0.0, "D": 0.0, "A": 0.0}

        for ev in events_list:
            h_sim = match_similarity(h_clean, ev["home_clean"])
            a_sim = match_similarity(a_clean, ev["away_clean"])
            avg_sim = (h_sim + a_sim) / 2.0

            if avg_sim > best_score and avg_sim >= 0.70:
                best_score = avg_sim
                best_prices = ev["prices"]

        return best_prices