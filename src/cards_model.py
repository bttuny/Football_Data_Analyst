# src/cards_model.py
import numpy as np
import pandas as pd
from scipy.stats import poisson
from typing import Dict, Any

class PremierLeagueCardsModel:
    def __init__(self):
        self.league_avg_cards = 4.0
        self.referee_multipliers = {}
        self.team_home_intensity = {}
        self.team_away_intensity = {}
        self.league_red_card_rate = 0.12

    def fit(self, df_cards: pd.DataFrame):
        """
        Kouluttaa korttimallin toteutuneesta tilastodatasta.
        """
        if df_cards.empty:
            return

        # 1. Liigan kokonaiskeskiarvot
        self.league_avg_cards = float(df_cards['total_cards'].mean())
        avg_home_cards = float(df_cards['home_cards'].mean())
        avg_away_cards = float(df_cards['away_cards'].mean())
        self.league_red_card_rate = float(df_cards['red_cards'].mean())

        # 2. Tuomarien laskenta (Bayes-shrinkage mukana)
        ref_counts = df_cards['Referee'].value_counts()
        for ref, count in ref_counts.items():
            ref_matches = df_cards[df_cards['Referee'] == ref]
            raw_avg = ref_matches['total_cards'].mean()
            raw_multiplier = raw_avg / self.league_avg_cards
            
            # Kutistus: Alle 6 ottelua viheltäneitä tuomareita vedetään kohti keskiarvoa 1.0
            weight = min(1.0, count / 6.0)
            self.referee_multipliers[ref] = float(weight * raw_multiplier + (1.0 - weight) * 1.0)

        # 3. Joukkueiden kortti-intensiteetti
        teams = set(df_cards['HomeTeam']).union(set(df_cards['AwayTeam']))
        for team in teams:
            h_games = df_cards[df_cards['HomeTeam'] == team]
            a_games = df_cards[df_cards['AwayTeam'] == team]

            self.team_home_intensity[team] = float(h_games['home_cards'].mean() / avg_home_cards) if len(h_games) > 0 else 1.0
            self.team_away_intensity[team] = float(a_games['away_cards'].mean() / avg_away_cards) if len(a_games) > 0 else 1.0

    def predict_cards(self, home_team: str, away_team: str, referee: str = None) -> Dict[str, Any]:
        ref_factor = self.referee_multipliers.get(referee, 1.0)
        
        # Joukkueiden kertoimet
        h_intensity = self.team_home_intensity.get(home_team, 1.0)
        a_intensity = self.team_away_intensity.get(away_team, 1.0)

        # Lasketaan odotusarvo
        expected_cards = self.league_avg_cards * ((h_intensity + a_intensity) / 2.0) * ref_factor
        expected_cards = max(1.5, min(8.0, expected_cards)) # järkevät rajat

        # Poisson-todennäköisyydet
        prob_under_3_5 = poisson.cdf(3, expected_cards)
        prob_over_3_5 = 1.0 - prob_under_3_5

        prob_under_4_5 = poisson.cdf(4, expected_cards)
        prob_over_4_5 = 1.0 - prob_under_4_5

        prob_red = 1.0 - poisson.pmf(0, self.league_red_card_rate * ref_factor)

        return {
            "referee": referee if referee else "Liigan keskiarvo",
            "expected_total_cards": round(float(expected_cards), 2),
            "prob_over_3_5": round(float(prob_over_3_5), 4),
            "prob_under_3_5": round(float(prob_under_3_5), 4),
            "prob_over_4_5": round(float(prob_over_4_5), 4),
            "prob_under_4_5": round(float(prob_under_4_5), 4),
            "prob_red_card": round(float(prob_red), 4),
            "fair_odds_over_3_5": round(1.0 / prob_over_3_5, 2) if prob_over_3_5 > 0 else 0,
            "fair_odds_over_4_5": round(1.0 / prob_over_4_5, 2) if prob_over_4_5 > 0 else 0
        }