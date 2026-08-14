# src/quant/cards_model.py
import re
import unicodedata
import numpy as np
import pandas as pd
from scipy.stats import poisson


def clean_name(text: str) -> str:
    if not text:
        return ""
    n = unicodedata.normalize("NFKD", str(text))
    n = "".join(c for c in n if not unicodedata.combining(c)).lower().strip()
    for noise in [
        "fc",
        "cf",
        "rcd",
        "rc",
        "ca",
        "cd",
        "de",
        "balompie",
        "futbol",
        "club",
        "afc",
        "madrid",
    ]:
        n = re.sub(rf"\b{noise}\b", "", n).strip()
    return re.sub(r"\s+", " ", n).strip()


class PremierLeagueCardsModel:

    def __init__(self):
        self.league_avg_cards = 4.40
        self.referee_factors = {}
        self.team_card_factors = {}

    def fit(self, historical_cards_df: pd.DataFrame):
        if historical_cards_df.empty:
            return

        total_matches = len(historical_cards_df)
        total_cards = historical_cards_df["total_cards"].sum()
        if total_matches > 0:
            self.league_avg_cards = float(total_cards / total_matches)

        df = historical_cards_df.copy()
        df["HomeClean"] = df["HomeTeam"].apply(clean_name)
        df["AwayClean"] = df["AwayTeam"].apply(clean_name)
        df["RefClean"] = df["Referee"].apply(clean_name)

        # Tuomarikertoimet Bayes-kutistuksella
        ref_stats = (
            df.groupby("RefClean")
            .agg(matches=("total_cards", "count"), cards=("total_cards", "mean"))
            .reset_index()
        )

        k = 8.0
        for _, row in ref_stats.iterrows():
            ref = row["RefClean"]
            n = row["matches"]
            mean_c = row["cards"]
            shrunk_factor = (n * (mean_c / self.league_avg_cards) + k * 1.0) / (
                n + k
            )
            self.referee_factors[ref] = float(shrunk_factor)

        # Joukkuekertoimet
        home_cards = df.groupby("HomeClean")["home_cards"].mean()
        away_cards = df.groupby("AwayClean")["away_cards"].mean()
        all_teams = set(home_cards.index).union(set(away_cards.index))

        for t in all_teams:
            h_c = home_cards.get(t, self.league_avg_cards / 2.0)
            a_c = away_cards.get(t, self.league_avg_cards / 2.0)
            team_avg = h_c + a_c
            self.team_card_factors[t] = float(team_avg / self.league_avg_cards)

    def predict_cards(
        self, home_team: str, away_team: str, referee: str = None
    ) -> dict:
        h_clean = clean_name(home_team)
        a_clean = clean_name(away_team)

        # Etsitään lähin joukkueosuma
        h_key = next(
            (k for k in self.team_card_factors if k in h_clean or h_clean in k),
            h_clean,
        )
        a_key = next(
            (k for k in self.team_card_factors if k in a_clean or a_clean in k),
            a_clean,
        )

        h_factor = self.team_card_factors.get(h_key, 1.0)
        a_factor = self.team_card_factors.get(a_key, 1.0)
        teams_factor = (h_factor + a_factor) / 2.0

        ref_factor = 1.0
        ref_display = "Liigan keskiarvo"
        if referee:
            ref_clean = clean_name(referee)
            matched_ref = next(
                (
                    k
                    for k in self.referee_factors
                    if k in ref_clean or ref_clean in k
                ),
                None,
            )
            if matched_ref:
                ref_factor = self.referee_factors[matched_ref]
                ref_display = f"{referee} ({ref_factor:.2f}x)"
            else:
                ref_display = referee

        lambda_cards = self.league_avg_cards * teams_factor * ref_factor
        lambda_cards = max(2.0, min(9.5, lambda_cards))

        # Lasketaan 5 linjaa: 2.5, 3.5, 4.5, 5.5, 6.5
        lines = {}
        for line in [2.5, 3.5, 4.5, 5.5, 6.5]:
            k = int(line)
            prob_over = 1.0 - float(poisson.cdf(k, lambda_cards))
            fair_odds = (
                round(1.0 / prob_over, 2) if prob_over > 0.01 else 99.0
            )
            key = f"over_{str(line).replace('.', '_')}"
            lines[key] = {
                "line": line,
                "prob": round(prob_over, 3),
                "prob_pct": int(round(prob_over * 100)),
                "fair_odds": fair_odds,
            }

        return {
            "expected_total_cards": round(lambda_cards, 2),
            "referee": ref_display,
            "lines": lines,
            "prob_over_3_5": lines["over_3_5"]["prob"],
            "fair_odds_over_3_5": lines["over_3_5"]["fair_odds"],
        }