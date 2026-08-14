# src/quant/cards_model.py
import pandas as pd
from scipy.stats import poisson

class PremierLeagueCardsModel:
    def __init__(self):
        self.league_avg_cards = 4.10
        self.referee_multipliers = {}
        self.team_home_intensity = {}
        self.team_away_intensity = {}
        self.league_red_card_rate = 0.12

    def fit(self, df_cards: pd.DataFrame):
        if df_cards.empty:
            return

        self.league_avg_cards = float(df_cards['total_cards'].mean())
        avg_h = float(df_cards['home_cards'].mean())
        avg_a = float(df_cards['away_cards'].mean())
        self.league_red_card_rate = float(df_cards['red_cards'].mean())

        # Tuomarien ankaruuskertoimet oikeasta datasta
        ref_counts = df_cards['Referee'].value_counts()
        for ref, count in ref_counts.items():
            raw_avg = df_cards[df_cards['Referee'] == ref]['total_cards'].mean()
            # Bayes-kutistus: Jos tuomarilla on vähän pelejä, arvo vedetään kohti keskiarvoa 1.0
            weight = min(1.0, count / 8.0)
            self.referee_multipliers[ref.lower()] = float(weight * (raw_avg / self.league_avg_cards) + (1.0 - weight))

        # Joukkueiden korttitaipumus oikeasta datasta
        teams = set(df_cards['HomeTeam']).union(set(df_cards['AwayTeam']))
        for team in teams:
            h_games = df_cards[df_cards['HomeTeam'] == team]
            a_games = df_cards[df_cards['AwayTeam'] == team]
            
            self.team_home_intensity[team.lower()] = float(h_games['home_cards'].mean() / avg_h) if len(h_games) > 0 else 1.0
            self.team_away_intensity[team.lower()] = float(a_games['away_cards'].mean() / avg_a) if len(a_games) > 0 else 1.0

    def predict_cards(self, home_team: str, away_team: str, referee: str = None) -> dict:
        ref_key = referee.lower() if referee else None
        ref_factor = self.referee_multipliers.get(ref_key, 1.0)
        
        # Haetaan joukkueiden kertoimet joustavalla nimenetsinnällä
        h_factor = next((v for k, v in self.team_home_intensity.items() if k in home_team.lower() or home_team.lower() in k), 1.0)
        a_factor = next((v for k, v in self.team_away_intensity.items() if k in away_team.lower() or away_team.lower() in k), 1.0)

        exp_cards = max(1.5, min(8.0, self.league_avg_cards * ((h_factor + a_factor) / 2.0) * ref_factor))
        prob_over_3_5 = 1.0 - poisson.cdf(3, exp_cards)
        prob_red = 1.0 - poisson.pmf(0, self.league_red_card_rate * ref_factor)

        return {
            "referee": referee if referee else "Liigan keskiarvo",
            "expected_total_cards": round(float(exp_cards), 2),
            "prob_over_3_5": round(float(prob_over_3_5), 4),
            "prob_red_card": round(float(prob_red), 4),
            "fair_odds_over_3_5": round(1.0 / prob_over_3_5, 2) if prob_over_3_5 > 0 else 0
        }