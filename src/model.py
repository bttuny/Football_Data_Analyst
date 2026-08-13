import numpy as np
import pandas as pd
from scipy.stats import poisson

class PremierLeaguePoissonModel:
    def __init__(self):
        self.home_attack = {}
        self.home_defense = {}
        self.away_attack = {}
        self.away_defense = {}
        self.league_avg_home_goals = 0.0
        self.league_avg_away_goals = 0.0

    def fit(self, df_matches: pd.DataFrame):
        """
        Teaches the model using historical match data.
        df_matches: includes columns: 'home_team', 'away_team', 'home_goals', 'away_goals'
        """
        #Calculate league averages
        self.league_avg_home_goals = df_matches['home_goals'].mean()
        self.league_avg_away_goals = df_matches['away_goals'].mean()

        teams = set(df_matches['home_team']).union(set(df_matches['away_team']))

        for team in teams:
            # Home games
            home_games = df_matches[df_matches['home_team'] == team]
            if len(home_games) > 0:
                self.home_attack[team] = home_games['home_goals'].mean() / self.league_avg_home_goals
                self.home_defense[team] = home_games['away_goals'].mean() / self.league_avg_away_goals
            else:
                self.home_attack[team] = 1.0
                self.home_defense[team] = 1.0

            # Away games
            away_games = df_matches[df_matches['away_team'] == team]
            if len(away_games) > 0:
                self.away_attack[team] = away_games['away_goals'].mean() / self.league_avg_away_goals
                self.away_defense[team] = away_games['home_goals'].mean() / self.league_avg_home_goals
            else:
                self.away_attack[team] = 1.0
                self.away_defense[team] = 1.0

    def predict_match(self, home_team: str, away_team: str, max_goals: int = 10):
        """
        Predicts the outcome of a match between home_team and away_team.
        Returns expected goals and probabilities for home win, draw, and away win.
        """
        # Get team strengths
        h_att = self.home_attack.get(home_team, 1.0)
        a_def = self.away_defense.get(away_team, 1.0)
        a_att = self.away_attack.get(away_team, 1.0)
        h_def = self.home_defense.get(home_team, 1.0)

        # Compute expected goals using the Poisson model
        lambda_home = h_att * a_def * self.league_avg_home_goals
        lambda_away = a_att * h_def * self.league_avg_away_goals

        # Poisson probabilities for each possible scoreline
        home_probs = poisson.pmf(np.arange(0, max_goals), lambda_home)
        away_probs = poisson.pmf(np.arange(0, max_goals), lambda_away)
        
        # Score probability matrix
        matrix = np.outer(home_probs, away_probs)

        # 1X2 probabilities
        prob_draw = float(np.sum(np.diag(matrix)))
        prob_home_win = float(np.sum(np.tril(matrix, -1)))
        prob_away_win = float(np.sum(np.triu(matrix, 1)))

        return {
            "home_team": home_team,
            "away_team": away_team,
            "expected_goals_home": round(float(lambda_home), 2),
            "expected_goals_away": round(float(lambda_away), 2),
            "prob_home_win": round(prob_home_win, 4),
            "prob_draw": round(prob_draw, 4),
            "prob_away_win": round(prob_away_win, 4)
        }

            