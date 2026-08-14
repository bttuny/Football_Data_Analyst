# src/quant/cards_model.py
from scipy.stats import poisson
import numpy as np
import pandas as pd

class PremierLeagueCardsModel:
    def __init__(self):
        self.league_avg_cards = 4.10
        self.referee_factors = {}
        self.team_card_factors = {}

    def fit(self, historical_cards_df: pd.DataFrame):
        if historical_cards_df.empty:
            return

        total_matches = len(historical_cards_df)
        total_cards = historical_cards_df['total_cards'].sum()
        if total_matches > 0:
            self.league_avg_cards = float(total_cards / total_matches)

        # Tuomarikertoimet Bayes-kutistuksella
        ref_stats = historical_cards_df.groupby('Referee').agg(
            matches=('total_cards', 'count'),
            cards=('total_cards', 'mean')
        ).reset_index()

        k = 10.0  # Kutistusparametri
        for _, row in ref_stats.iterrows():
            ref = row['Referee']
            n = row['matches']
            mean_c = row['cards']
            shrunk_factor = (n * (mean_c / self.league_avg_cards) + k * 1.0) / (n + k)
            self.referee_factors[ref.lower()] = float(shrunk_factor)

        # Joukkuekohtaiset kertoimet
        home_cards = historical_cards_df.groupby('HomeTeam')['home_cards'].mean()
        away_cards = historical_cards_df.groupby('AwayTeam')['away_cards'].mean()
        all_teams = set(home_cards.index).union(set(away_cards.index))

        for t in all_teams:
            h_c = home_cards.get(t, self.league_avg_cards / 2)
            a_c = away_cards.get(t, self.league_avg_cards / 2)
            team_avg = (h_c + a_c)
            self.team_card_factors[t.lower()] = float(team_avg / self.league_avg_cards)

    def predict_cards(self, home_team: str, away_team: str, referee: str = None) -> dict:
        h_factor = self.team_card_factors.get(home_team.lower(), 1.0)
        a_factor = self.team_card_factors.get(away_team.lower(), 1.0)
        teams_factor = (h_factor + a_factor) / 2.0

        ref_factor = 1.0
        ref_display = "Liigan keskiarvo"
        if referee:
            ref_clean = referee.strip().lower()
            if ref_clean in self.referee_factors:
                ref_factor = self.referee_factors[ref_clean]
                ref_display = f"{referee} ({ref_factor:.2f}x)"
            else:
                ref_display = referee

        lambda_cards = self.league_avg_cards * teams_factor * ref_factor
        lambda_cards = max(1.5, min(8.0, lambda_cards))

        # Lasketaan todennäköisyydet ja reilut kertoimet linjoille 2.5, 3.5, 4.5, 5.5
        lines = {}
        for line in [2.5, 3.5, 4.5, 5.5]:
            k = int(line)  # 2, 3, 4, 5
            prob_over = 1.0 - float(poisson.cdf(k, lambda_cards))
            fair_odds = round(1.0 / prob_over, 2) if prob_over > 0.01 else 99.0
            
            # Käytetään selkeitä avaimia: over_2_5, over_3_5, over_4_5, over_5_5
            key = f"over_{str(line).replace('.', '_')}"
            lines[key] = {
                "line": line,
                "prob": round(prob_over, 3),
                "prob_pct": int(round(prob_over * 100)),
                "fair_odds": fair_odds
            }

        return {
            "expected_total_cards": round(lambda_cards, 2),
            "referee": ref_display,
            "lines": lines,
            "prob_over_3_5": lines["over_3_5"]["prob"],
            "fair_odds_over_3_5": lines["over_3_5"]["fair_odds"]
        }