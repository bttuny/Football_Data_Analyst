# src/quant/poisson_dixon.py
import numpy as np
import pandas as pd
from scipy.stats import poisson
import unicodedata
import re

def clean_team_name(text: str) -> str:
    if not text or pd.isna(text):
        return ""
    
    # 1. Poistetaan erikoismerkit ja aksentit (esim. Atlético -> Atletico, Coruña -> Coruna)
    orig = unicodedata.normalize("NFKD", text)
    orig = "".join(c for c in orig if not unicodedata.combining(c)).lower().strip()
    
    # 2. Hardkoodatut korjaukset (Yhdistää API-nimet historiadatan nimiin)
    mapping = {
        "ath madrid": "atletico madrid",
        "club atletico de madrid": "atletico madrid",
        "rcd espanyol de barcelona": "espanol",
        "espanyol": "espanol",
        "rc deportivo la coruna": "deportivo la coruna",
        "la coruna": "deportivo la coruna",
        "real racing club de santander": "racing santander",
        "racing": "racing santander",
        "real betis balompie": "betis",
        "rayo vallecano de madrid": "rayo vallecano",
        "real valladolid cf": "valladolid",
        "real sporting de gijon": "sporting gijon",
        "olympique de marseille": "marseille",
        "paris saint germain": "psg",
        "bayer 04 leverkusen": "bayer leverkusen",
        "fc bayern munchen": "bayern munich",
        "borussia monchengladbach": "monchengladbach",
        "1. fsv mainz 05": "mainz",
        "1. fc union berlin": "union berlin",
        "eintracht frankfurt": "eintracht frankfurt",
        "fc schalke 04": "schalke",
        "vfb stuttgart": "stuttgart",
        "juventus fc": "juventus",
        "fc internazionale milano": "inter",
        "inter milan": "inter",
        "nottingham forest fc": "nottingham forest",
        "wolverhampton wanderers fc": "wolves",
        "wolverhampton wanderers": "wolves",
        "manchester united fc": "man united",
        "manchester city fc": "man city",
        "newcastle united fc": "newcastle",
        "tottenham hotspur fc": "tottenham",
    }
    
    for k, v in mapping.items():
        if k in orig:
            orig = v
            
    # 3. Yleisten turhien päätteiden siivous
    n = orig
    for noise in [
        "fc", "cf", "rcd", "rc", "ca", "cd", "de", "balompie",
        "futbol", "club", "afc", "sad", "ac", "as", "ogc", "stade", "sc", "1.", "04", "05"
    ]:
        n = re.sub(rf"\b{noise}\b", "", n).strip()
        
    n = re.sub(r"\s+", " ", n).strip()
    
    if len(n) < 3:
        return orig
    return n


class PremierLeaguePoissonModel:
    def __init__(self):
        self.rho = -0.05  # Dixon-Coles korjaus (Tasapelien todennäköisyys hieman luontaista suurempi)
        self.global_home_goals = 1.5
        self.global_away_goals = 1.1
        self.team_stats = {}

    def fit(self, df: pd.DataFrame):
        if df is None or df.empty:
            return

        d = df.copy()
        
        # Nimien siivous yhdenmukaiseksi
        d["home_team"] = d["home_team"].apply(clean_team_name)
        d["away_team"] = d["away_team"].apply(clean_team_name)

        # AIKAPAINOTUS MAALEILLE (450 päivän puoliintumisaika)
        if "datetime" in d.columns:
            d["parsed_date"] = pd.to_datetime(d["datetime"], errors="coerce", utc=True)
        elif "Date" in d.columns:
            d["parsed_date"] = pd.to_datetime(d["Date"], dayfirst=True, errors="coerce", utc=True)
        else:
            d["parsed_date"] = pd.NaT

        max_date = d["parsed_date"].max()
        if max_date is pd.NaT or pd.isna(max_date) is True:
            d["weight"] = 1.0
        else:
            decay_rate = np.log(2) / 450.0  
            days_ago = (max_date - d["parsed_date"]).dt.days.fillna(0)
            days_ago = np.clip(days_ago, 0, None)
            d["weight"] = np.exp(-decay_rate * days_ago)

        d = d.dropna(subset=["home_goals", "away_goals"])
        d["home_goals"] = d["home_goals"].astype(float)
        d["away_goals"] = d["away_goals"].astype(float)

        w_sum = d["weight"].sum()
        if w_sum > 0:
            self.global_home_goals = np.average(d["home_goals"], weights=d["weight"])
            self.global_away_goals = np.average(d["away_goals"], weights=d["weight"])
        else:
            self.global_home_goals = d["home_goals"].mean()
            self.global_away_goals = d["away_goals"].mean()

        d["w_hg"] = d["home_goals"] * d["weight"]
        d["w_ag"] = d["away_goals"] * d["weight"]
        
        # KOTITILASTOT: Tehdyt maalit (Attack) ja Päästetyt maalit (Defense)
        home_agg = d.groupby("home_team").agg(
            w_sum=("weight", "sum"), wt_hg=("w_hg", "sum"), wt_ag=("w_ag", "sum")
        )
        
        # VIERASTILASTOT: Tehdyt maalit (Attack) ja Päästetyt maalit (Defense)
        away_agg = d.groupby("away_team").agg(
            w_sum=("weight", "sum"), wt_hg=("w_hg", "sum"), wt_ag=("w_ag", "sum")
        )

        all_teams = set(home_agg.index).union(set(away_agg.index))
        
        for t in all_teams:
            # Kotipelien keskiarvot
            h_w = home_agg.loc[t, "w_sum"] if t in home_agg.index else 0
            if h_w > 0:
                avg_scored_home = home_agg.loc[t, "wt_hg"] / h_w
                avg_conceded_home = home_agg.loc[t, "wt_ag"] / h_w
            else:
                avg_scored_home = self.global_home_goals
                avg_conceded_home = self.global_away_goals
                
            # Vieraspelejen keskiarvot
            a_w = away_agg.loc[t, "w_sum"] if t in away_agg.index else 0
            if a_w > 0:
                avg_scored_away = away_agg.loc[t, "wt_ag"] / a_w
                avg_conceded_away = away_agg.loc[t, "wt_hg"] / a_w
            else:
                avg_scored_away = self.global_away_goals
                avg_conceded_away = self.global_home_goals
                
            self.team_stats[t] = {
                "home_att": avg_scored_home / self.global_home_goals,
                "home_def": avg_conceded_home / self.global_away_goals,
                "away_att": avg_scored_away / self.global_away_goals,
                "away_def": avg_conceded_away / self.global_home_goals,
                "home_games": h_w,
                "away_games": a_w

            }


    def predict_match(self, home_team: str, away_team: str) -> dict:
        ht_clean = clean_team_name(home_team)
        at_clean = clean_team_name(away_team)

        h_key = next((k for k in self.team_stats if len(k) > 2 and (k in ht_clean or ht_clean in k)), None)
        a_key = next((k for k in self.team_stats if len(k) > 2 and (k in at_clean or at_clean in k)), None)

        PROMOTED_HOME_ATT = 0.85
        PROMOTED_HOME_DEF = 1.15
        PROMOTED_AWAY_ATT = 0.65
        PROMOTED_AWAY_DEF = 1.35

        # Haetaan raakadatan pelimäärät ja voimaluvut
        h_hg = self.team_stats[h_key]["home_games"] if h_key else 0.0
        a_ag = self.team_stats[a_key]["away_games"] if a_key else 0.0
        h_tot = (self.team_stats[h_key]["home_games"] + self.team_stats[h_key]["away_games"]) if h_key else 0.0
        a_tot = (self.team_stats[a_key]["home_games"] + self.team_stats[a_key]["away_games"]) if a_key else 0.0

        h_att_raw = self.team_stats[h_key]["home_att"] if h_key else PROMOTED_HOME_ATT
        h_def_raw = self.team_stats[h_key]["home_def"] if h_key else PROMOTED_HOME_DEF
        a_att_raw = self.team_stats[a_key]["away_att"] if a_key else PROMOTED_AWAY_ATT
        a_def_raw = self.team_stats[a_key]["away_def"] if a_key else PROMOTED_AWAY_DEF

        # ---------------------------------------------------------
        # BAYESILAINEN KUTISTUS (Estää ylireagoinnin yksittäisiin peleihin)
        # prior_weight = 5.0 tarkoittaa, että ankkuri vastaa 5 ottelun painoarvoa
        prior_weight = 5.0 
        
        # Jos joukkueella on yli 15 peliä historiassa, ankkurina käytetään liigan keskiarvoa (1.0).
        # Jos alle 15 (esim. nousija), ankkurina käytetään kovaa rangaistusta.
        h_prior_att = 1.0 if h_tot > 15 else PROMOTED_HOME_ATT
        h_prior_def = 1.0 if h_tot > 15 else PROMOTED_HOME_DEF
        a_prior_att = 1.0 if a_tot > 15 else PROMOTED_AWAY_ATT
        a_prior_def = 1.0 if a_tot > 15 else PROMOTED_AWAY_DEF

        # Lasketaan lopulliset, turvalliset voimaluvut yhdistämällä raakadata ja ankkuri
        h_att = (h_att_raw * h_hg + h_prior_att * prior_weight) / (h_hg + prior_weight)
        h_def = (h_def_raw * h_hg + h_prior_def * prior_weight) / (h_hg + prior_weight)
        
        a_att = (a_att_raw * a_ag + a_prior_att * prior_weight) / (a_ag + prior_weight)
        a_def = (a_def_raw * a_ag + a_prior_def * prior_weight) / (a_ag + prior_weight)
        # ---------------------------------------------------------

        # UUSI MAALIODOTTAMAN LASKENTA (Vastustajan koti/vieraspuolustus huomioitu!)
        lambda_home = self.global_home_goals * h_att * a_def
        lambda_away = self.global_away_goals * a_att * h_def
        
        # Rajoitetaan arvot realistisiksi (0.20 - 5.00 maalia)
        lambda_home = max(0.2, min(5.0, lambda_home))
        lambda_away = max(0.2, min(5.0, lambda_away))
        
        max_goals = 10
        prob_matrix = np.zeros((max_goals, max_goals))
        
        for i in range(max_goals):
            for j in range(max_goals):
                p = poisson.pmf(i, lambda_home) * poisson.pmf(j, lambda_away)
                
                # Dixon-Coles riippuvuuskorjaus mataliin maalimääriin
                if i == 0 and j == 0:
                    p *= (1 - lambda_home * lambda_away * self.rho)
                elif i == 0 and j == 1:
                    p *= (1 + lambda_home * self.rho)
                elif i == 1 and j == 0:
                    p *= (1 + lambda_away * self.rho)
                elif i == 1 and j == 1:
                    p *= (1 - self.rho)
                    
                prob_matrix[i, j] = max(0, p)
                
        prob_matrix /= np.sum(prob_matrix) # Normalisointi, jotta summa on tasan 1.0 (100%)
        
        prob_home = np.sum(np.tril(prob_matrix, -1))
        prob_draw = np.trace(prob_matrix)
        prob_away = np.sum(np.triu(prob_matrix, 1))
        
        return {
            "expected_goals_home": round(float(lambda_home), 2),
            "expected_goals_away": round(float(lambda_away), 2),
            "prob_home_win": round(float(prob_home), 4),
            "prob_draw": round(float(prob_draw), 4),
            "prob_away_win": round(float(prob_away), 4),
        }