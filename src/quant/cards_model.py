# src/quant/cards_model.py
import re
import unicodedata
from typing import Optional
import numpy as np
import pandas as pd
from scipy.stats import poisson, nbinom

def clean_name(text: Optional[str]) -> str:
    if not text or pd.isna(text):
        return ""
    
    orig = unicodedata.normalize("NFKD", text)
    orig = "".join(c for c in orig if not unicodedata.combining(c)).lower().strip()
    
    orig = orig.replace("ath madrid", "atletico madrid")
    orig = orig.replace("espanyol", "espanol")
    
    n = orig
    for noise in [
        "fc", "cf", "rcd", "rc", "ca", "cd", "de", "balompie",
        "futbol", "club", "afc", "deportivo", "sad",
        "ac", "as", "ogc", "stade", "sc"
    ]:
        n = re.sub(rf"\b{noise}\b", "", n).strip()
        
    n = re.sub(r"\s+", " ", n).strip()
    
    if len(n) < 3:
        return orig
    return n

class PremierLeagueCardsModel:

    def __init__(self):
        self.league_avg_cards = 4.40
        self.dispersion_alpha = 0.08  # NegBinom dispersion: Var(Y) = mu + alpha * mu^2
        self.referee_factors = {}
        self.team_card_factors = {}

    def fit(self, historical_cards_df: pd.DataFrame):
        if historical_cards_df is None or historical_cards_df.empty:
            return

        # Tehdään heti kopio, jotta vältetään fragmentaatio
        df = historical_cards_df.copy()

        # 1. AIKAPAINOTUS (Exponential Time Decay)
        if "Date" in df.columns:
            df["parsed_date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
            max_date = df["parsed_date"].max()
            
            if max_date is pd.NaT or pd.isna(max_date) is True:
                df["weight"] = 1.0
            else:
                decay_rate = np.log(2) / 365.0  # 50% painoarvo laskee 365 päivässä
                days_ago = (max_date - df["parsed_date"]).dt.days.fillna(0)
                days_ago = np.clip(days_ago, 0, None)
                df["weight"] = np.exp(-decay_rate * days_ago)
        else:
            df["weight"] = 1.0

        # 2. Liigan painotettu korttikeskiarvo ja varianssi (Negatiivisen binomijakauman dispersio alpha)
        weight_sum = df["weight"].sum()
        if weight_sum > 0:
            self.league_avg_cards = float(np.average(df["total_cards"], weights=df["weight"]))
            # Painotettu varianssi
            weighted_var = float(np.average((df["total_cards"] - self.league_avg_cards) ** 2, weights=df["weight"]))
        else:
            total_matches = len(df)
            if total_matches > 0:
                self.league_avg_cards = float(np.mean(df["total_cards"].to_numpy()))
                weighted_var = float(np.var(df["total_cards"].to_numpy()))
            else:
                weighted_var = self.league_avg_cards * 1.3

        # Estimoidaan dispersioparametri alpha: Var = mu + alpha * mu^2 -> alpha = (Var - mu) / mu^2
        if self.league_avg_cards > 0:
            raw_alpha = (weighted_var - self.league_avg_cards) / (self.league_avg_cards ** 2)
            self.dispersion_alpha = float(np.clip(raw_alpha, 0.03, 0.35))
        else:
            self.dispersion_alpha = 0.08

        df["HomeClean"] = df["HomeTeam"].apply(clean_name)
        df["AwayClean"] = df["AwayTeam"].apply(clean_name)
        df["RefClean"] = df["Referee"].apply(clean_name)

        # Lasketaan valmiiksi painotetut summat vektoreina (Poistaa PerformanceWarningin!)
        df["weighted_total"] = df["total_cards"] * df["weight"]
        df["weighted_home"] = df["home_cards"] * df["weight"]
        df["weighted_away"] = df["away_cards"] * df["weight"]

        # 3. Tuomarikertoimet (Painotettu keskiarvo + Bayes-kutistus k=8)
        valid_refs = df[~df["RefClean"].isin(["unknown", "nan", ""])].copy()
        
        ref_stats = valid_refs.groupby("RefClean").agg(
            matches=("total_cards", "count"),
            w_sum=("weight", "sum"),
            wt_sum=("weighted_total", "sum")
        ).reset_index()

        ref_stats["cards"] = np.where(
            ref_stats["w_sum"] > 0,
            ref_stats["wt_sum"] / ref_stats["w_sum"],
            self.league_avg_cards
        )

        k = 8.0
        shrunk_factors = (ref_stats["matches"] * (ref_stats["cards"] / self.league_avg_cards) + k * 1.0) / (ref_stats["matches"] + k)
        self.referee_factors = dict(zip(ref_stats["RefClean"].astype(str), shrunk_factors.astype(float)))

        # 4. Joukkuekertoimet (Painotettu keskiarvo vektoreilla)
        home_stats = df.groupby("HomeClean").agg(w_sum=("weight", "sum"), wt_sum=("weighted_home", "sum"))
        home_cards = pd.Series(
            np.where(home_stats["w_sum"] > 0, home_stats["wt_sum"] / home_stats["w_sum"], self.league_avg_cards / 2.0),
            index=home_stats.index
        )

        away_stats = df.groupby("AwayClean").agg(w_sum=("weight", "sum"), wt_sum=("weighted_away", "sum"))
        away_cards = pd.Series(
            np.where(away_stats["w_sum"] > 0, away_stats["wt_sum"] / away_stats["w_sum"], self.league_avg_cards / 2.0),
            index=away_stats.index
        )
        
        all_teams = set(home_cards.index).union(set(away_cards.index))

        for t in all_teams:
            h_c = float(home_cards.get(t, self.league_avg_cards / 2.0) or (self.league_avg_cards / 2.0))
            a_c = float(away_cards.get(t, self.league_avg_cards / 2.0) or (self.league_avg_cards / 2.0))
            team_avg = h_c + a_c
            self.team_card_factors[t] = team_avg / self.league_avg_cards

    def predict_cards(
        self, home_team: str, away_team: str, referee: Optional[str] = None
    ) -> dict:
        h_clean = clean_name(home_team)
        a_clean = clean_name(away_team)

        # Joukkueosumien haku sanakirjasta
        h_key = next((k for k in self.team_card_factors if len(k) > 2 and (k in h_clean or h_clean in k)), None)
        a_key = next((k for k in self.team_card_factors if len(k) > 2 and (k in a_clean or a_clean in k)), None)

        h_factor = self.team_card_factors.get(h_key, 1.0) if h_key else 1.0
        a_factor = self.team_card_factors.get(a_key, 1.0) if a_key else 1.0
        teams_factor = (h_factor + a_factor) / 2.0

        ref_factor = 1.0
        ref_display = "Joukkueiden KA (1.00x)"
        if referee:
            ref_clean = clean_name(referee)
            matched_ref = next(
                (k for k in self.referee_factors if len(k) > 2 and (k in ref_clean or ref_clean in k)),
                None,
            )
            if matched_ref:
                ref_factor = self.referee_factors[matched_ref]
                ref_display = f"{referee} ({ref_factor:.2f}x)"
            else:
                ref_display = referee

        lambda_cards = self.league_avg_cards * teams_factor * ref_factor
        lambda_cards = max(2.0, min(9.5, lambda_cards))

        # Negatiivinen binomijakauma: E[X] = mu = lambda_cards, Var[X] = mu + alpha * mu^2
        # scipy.stats.nbinom parametrit: n = 1 / alpha, p = 1 / (1 + alpha * mu)
        alpha = max(0.01, self.dispersion_alpha)
        nb_n = 1.0 / alpha
        nb_p = 1.0 / (1.0 + alpha * lambda_cards)

        poisson_lines = {}
        nbinom_lines = {}
        for line in [2.5, 3.5, 4.5, 5.5, 6.5]:
            k = int(line)
            
            # 1. Poisson
            prob_p_over = 1.0 - float(poisson.cdf(k, lambda_cards))
            fair_p_odds = round(1.0 / prob_p_over, 2) if prob_p_over > 0.01 else 99.0
            
            # 2. Negatiivinen binomi
            prob_nb_over = 1.0 - float(nbinom.cdf(k, nb_n, nb_p))
            fair_nb_odds = round(1.0 / prob_nb_over, 2) if prob_nb_over > 0.01 else 99.0

            key = f"over_{str(line).replace('.', '_')}"
            poisson_lines[key] = {
                "line": line,
                "prob": round(prob_p_over, 3),
                "prob_pct": round(prob_p_over * 100),
                "fair_odds": fair_p_odds,
            }
            nbinom_lines[key] = {
                "line": line,
                "prob": round(prob_nb_over, 3),
                "prob_pct": round(prob_nb_over * 100),
                "fair_odds": fair_nb_odds,
            }

        return {
            "expected_total_cards": round(lambda_cards, 2),
            "referee": ref_display,
            "dispersion_alpha": round(self.dispersion_alpha, 4),
            "lines": poisson_lines,
            "nbinom_lines": nbinom_lines,
            "prob_over_3_5": poisson_lines["over_3_5"]["prob"],
            "fair_odds_over_3_5": poisson_lines["over_3_5"]["fair_odds"],
            "nbinom_prob_over_3_5": nbinom_lines["over_3_5"]["prob"],
            "nbinom_fair_odds_over_3_5": nbinom_lines["over_3_5"]["fair_odds"],
        }