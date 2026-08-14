from datetime import datetime
import numpy as np
import pandas as pd
from scipy.stats import poisson

class PremierLeaguePoissonModel:

    def __init__(self, decay_rate: float = 0.003, rho: float = -0.13):
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

    def _tau_correction(
        self, x: int, y: int, lambda_h: float, lambda_a: float
    ) -> float:
        if x == 0 and y == 0:
            return 1.0 - (lambda_h * lambda_a * self.rho)
        elif x == 0 and y == 1:
            return 1.0 + (lambda_h * self.rho)
        elif x == 1 and y == 0:
            return 1.0 + (lambda_a * self.rho)
        elif x == 1 and y == 1:
            return 1.0 - self.rho
        return 1.0

    def fit(self, df_matches: pd.DataFrame, reference_date: datetime = None):
        if reference_date is None:
            reference_date = datetime.utcnow()

        df = df_matches.copy()
        if "date" in df.columns and not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            if df["date"].dt.tz is not None:
                df["date"] = df["date"].dt.tz_localize(None)
            ref_naive = reference_date.replace(tzinfo=None)
            days_ago = (ref_naive - df["date"]).dt.total_seconds() / (24 * 3600)
            df["weight"] = np.exp(-self.decay_rate * np.maximum(0, days_ago))
        else:
            df["weight"] = 1.0

        total_w = df["weight"].sum() if not df.empty else 1.0
        self.league_avg_home_goals = (
            (df["home_goals"] * df["weight"]).sum() / total_w
            if not df.empty
            else 1.50
        )
        self.league_avg_away_goals = (
            (df["away_goals"] * df["weight"]).sum() / total_w
            if not df.empty
            else 1.20
        )

        teams = (
            set(df["home_team"]).union(set(df["away_team"]))
            if not df.empty
            else set()
        )
        for team in teams:
            h_games = df[df["home_team"] == team]
            h_w = h_games["weight"].sum()
            if h_w > 0:
                raw_h_att = (
                    (h_games["home_goals"] * h_games["weight"]).sum()
                    / h_w
                    / self.league_avg_home_goals
                )
                raw_h_def = (
                    (h_games["away_goals"] * h_games["weight"]).sum()
                    / h_w
                    / self.league_avg_away_goals
                )
                cred = min(1.0, h_w / 10.0)
                self.home_attack[team] = (
                    cred * raw_h_att + (1 - cred) * self.PROMOTED_ATTACK
                )
                self.home_defense[team] = (
                    cred * raw_h_def + (1 - cred) * self.PROMOTED_DEFENSE
                )
            else:
                self.home_attack[team] = self.PROMOTED_ATTACK
                self.home_defense[team] = self.PROMOTED_DEFENSE

            a_games = df[df["away_team"] == team]
            a_w = a_games["weight"].sum()
            if a_w > 0:
                raw_a_att = (
                    (a_games["away_goals"] * a_games["weight"]).sum()
                    / a_w
                    / self.league_avg_away_goals
                )
                raw_a_def = (
                    (a_games["away_goals"] * a_games["weight"]).sum()
                    / a_w
                    / self.league_avg_home_goals
                )
                cred = min(1.0, a_w / 10.0)
                self.away_attack[team] = (
                    cred * raw_a_att + (1 - cred) * self.PROMOTED_ATTACK
                )
                self.away_defense[team] = (
                    cred * raw_a_def + (1 - cred) * self.PROMOTED_DEFENSE
                )
            else:
                self.away_attack[team] = self.PROMOTED_ATTACK
                self.away_defense[team] = self.PROMOTED_DEFENSE

    def predict_match(
        self, home_team: str, away_team: str, max_goals: int = 10
    ) -> dict:
        h_att = self.home_attack.get(home_team, self.PROMOTED_ATTACK)
        a_def = self.away_defense.get(away_team, self.PROMOTED_DEFENSE)
        a_att = self.away_attack.get(away_team, self.PROMOTED_ATTACK)
        h_def = self.home_defense.get(home_team, self.PROMOTED_DEFENSE)

        lambda_h = float(h_att * a_def * self.league_avg_home_goals)
        lambda_a = float(a_att * h_def * self.league_avg_away_goals)

        matrix = np.zeros((max_goals, max_goals))
        for x in range(max_goals):
            for y in range(max_goals):
                matrix[x, y] = (
                    poisson.pmf(x, lambda_h)
                    * poisson.pmf(y, lambda_a)
                    * self._tau_correction(x, y, lambda_h, lambda_a)
                )

        matrix = matrix / np.sum(matrix)

        return {
            "home_team": home_team,
            "away_team": away_team,
            "expected_goals_home": round(lambda_h, 2),
            "expected_goals_away": round(lambda_a, 2),
            "prob_home_win": round(float(np.sum(np.tril(matrix, -1))), 4),
            "prob_draw": round(float(np.sum(np.diag(matrix))), 4),
            "prob_away_win": round(float(np.sum(np.triu(matrix, 1))), 4),
        }