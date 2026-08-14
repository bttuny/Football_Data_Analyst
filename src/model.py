# src/model.py
from datetime import datetime
import numpy as np
import pandas as pd
from scipy.stats import poisson

class PremierLeaguePoissonModel:
    def __init__(self, decay_rate: float = 0.003, rho: float = -0.13):
        """
        decay_rate: Aikapainotuksen vaimennuskerroin per päivä.
        rho: Dixon-Coles -korjauskerroin matalamaalisille tuloksille.
        """
        self.decay_rate = decay_rate
        self.rho = rho
        self.home_attack = {}
        self.home_defense = {}
        self.away_attack = {}
        self.away_defense = {}
        
        self.PROMOTED_ATTACK = 0.65
        self.PROMOTED_DEFENSE = 1.45
        
        self.league_avg_home_goals = 1.50
        self.league_avg_away_goals = 1.20

    def _tau_correction(self, x: int, y: int, lambda_h: float, lambda_a: float) -> float:
        """Dixon-Coles matalamaalisten tulosten korjausfunktio"""
        if x == 0 and y == 0:
            return 1.0 - (lambda_h * lambda_a * self.rho)
        elif x == 0 and y == 1:
            return 1.0 + (lambda_h * self.rho)
        elif x == 1 and y == 0:
            return 1.0 + (lambda_a * self.rho)
        elif x == 1 and y == 1:
            return 1.0 - self.rho
        else:
            return 1.0

    def fit(self, df_matches: pd.DataFrame, reference_date: datetime = None):
        if reference_date is None:
            reference_date = datetime.utcnow()

        df = df_matches.copy()

        if 'date' in df.columns and not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            if df['date'].dt.tz is not None:
                df['date'] = df['date'].dt.tz_localize(None)
            ref_naive = reference_date.replace(tzinfo=None)
            
            days_ago = (ref_naive - df['date']).dt.total_seconds() / (24 * 3600)
            days_ago = np.maximum(0, days_ago)
            df['weight'] = np.exp(-self.decay_rate * days_ago)
        else:
            df['weight'] = 1.0

        total_weight = df['weight'].sum() if not df.empty else 1.0
        self.league_avg_home_goals = (df['home_goals'] * df['weight']).sum() / total_weight if not df.empty else 1.50
        self.league_avg_away_goals = (df['away_goals'] * df['weight']).sum() / total_weight if not df.empty else 1.20

        teams = set(df['home_team']).union(set(df['away_team'])) if not df.empty else set()

        for team in teams:
            home_games = df[df['home_team'] == team]
            h_weight = home_games['weight'].sum()
            if h_weight > 0:
                raw_h_att = (home_games['home_goals'] * home_games['weight']).sum() / h_weight / self.league_avg_home_goals
                raw_h_def = (home_games['away_goals'] * home_games['weight']).sum() / h_weight / self.league_avg_away_goals
                credibility = min(1.0, h_weight / 10.0)
                self.home_attack[team] = credibility * raw_h_att + (1 - credibility) * self.PROMOTED_ATTACK
                self.home_defense[team] = credibility * raw_h_def + (1 - credibility) * self.PROMOTED_DEFENSE
            else:
                self.home_attack[team] = self.PROMOTED_ATTACK
                self.home_defense[team] = self.PROMOTED_DEFENSE

            away_games = df[df['away_team'] == team]
            a_weight = away_games['weight'].sum()
            if a_weight > 0:
                raw_a_att = (away_games['away_goals'] * away_games['weight']).sum() / a_weight / self.league_avg_away_goals
                raw_a_def = (away_games['away_goals'] * away_games['weight']).sum() / a_weight / self.league_avg_home_goals
                credibility = min(1.0, a_weight / 10.0)
                self.away_attack[team] = credibility * raw_a_att + (1 - credibility) * self.PROMOTED_ATTACK
                self.away_defense[team] = credibility * raw_a_def + (1 - credibility) * self.PROMOTED_DEFENSE
            else:
                self.away_attack[team] = self.PROMOTED_ATTACK
                self.away_defense[team] = self.PROMOTED_DEFENSE

    def predict_match(self, home_team: str, away_team: str, max_goals: int = 10):
        h_att = self.home_attack.get(home_team, self.PROMOTED_ATTACK)
        a_def = self.away_defense.get(away_team, self.PROMOTED_DEFENSE)
        a_att = self.away_attack.get(away_team, self.PROMOTED_ATTACK)
        h_def = self.home_defense.get(home_team, self.PROMOTED_DEFENSE)

        lambda_home = float(h_att * a_def * self.league_avg_home_goals)
        lambda_away = float(a_att * h_def * self.league_avg_away_goals)

        # Rakennetaan korjattu todennäköisyysmatriisi
        matrix = np.zeros((max_goals, max_goals))
        for x in range(max_goals):
            for y in range(max_goals):
                p_x = poisson.pmf(x, lambda_home)
                p_y = poisson.pmf(y, lambda_away)
                tau = self._tau_correction(x, y, lambda_home, lambda_away)
                matrix[x, y] = p_x * p_y * tau

        # Normalisoidaan summa tasan 1.0:aan
        matrix = matrix / np.sum(matrix)

        prob_draw = float(np.sum(np.diag(matrix)))
        prob_home_win = float(np.sum(np.tril(matrix, -1)))
        prob_away_win = float(np.sum(np.triu(matrix, 1)))

        return {
            "home_team": home_team,
            "away_team": away_team,
            "expected_goals_home": round(lambda_home, 2),
            "expected_goals_away": round(lambda_away, 2),
            "prob_home_win": round(prob_home_win, 4),
            "prob_draw": round(prob_draw, 4),
            "prob_away_win": round(prob_away_win, 4)
        }