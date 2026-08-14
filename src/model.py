# src/model.py
from datetime import datetime
import numpy as np
import pandas as pd
from scipy.stats import poisson

class PremierLeaguePoissonModel:
    def __init__(self, decay_rate: float = 0.003):
        """
        decay_rate: Eksponentiaalinen vaimennuskerroin per päivä.
        0.003 antaa ~6 kk vanhalle ottelulle n. 58 % painon ja 1 v vanhalle ~33 % painon.
        """
        self.decay_rate = decay_rate
        self.home_attack = {}
        self.home_defense = {}
        self.away_attack = {}
        self.away_defense = {}
        
        # Valioliigan historialliset oletusarvot nousijajoukkueille
        self.PROMOTED_ATTACK = 0.80
        self.PROMOTED_DEFENSE = 1.25
        
        self.league_avg_home_goals = 1.50
        self.league_avg_away_goals = 1.20

    def fit(self, df_matches: pd.DataFrame, reference_date: datetime = None):
        """
        df_matches-sarakkeet: ['home_team', 'away_team', 'home_goals', 'away_goals', 'date']
        """
        if reference_date is None:
            reference_date = datetime.utcnow()

        df = df_matches.copy()

        # Lasketaan aikapainotus (Time-decay weights)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            # Poistetaan aikavyöhyke vertailua varten
            if df['date'].dt.tz is not None:
                df['date'] = df['date'].dt.tz_localize(None)
            ref_naive = reference_date.replace(tzinfo=None)
            
            days_ago = (ref_naive - df['date']).dt.total_seconds() / (24 * 3600)
            days_ago = np.maximum(0, days_ago)
            df['weight'] = np.exp(-self.decay_rate * days_ago)
        else:
            df['weight'] = 1.0

        # Painotetut liigakeskiarvot
        total_weight = df['weight'].sum()
        self.league_avg_home_goals = (df['home_goals'] * df['weight']).sum() / total_weight
        self.league_avg_away_goals = (df['away_goals'] * df['weight']).sum() / total_weight

        teams = set(df['home_team']).union(set(df['away_team']))

        for team in teams:
            # Kotipelit
            home_games = df[df['home_team'] == team]
            h_weight = home_games['weight'].sum()
            
            if h_weight > 0:
                # Painotettu keskiarvo
                raw_h_att = (home_games['home_goals'] * home_games['weight']).sum() / h_weight / self.league_avg_home_goals
                raw_h_def = (home_games['away_goals'] * home_games['weight']).sum() / h_weight / self.league_avg_away_goals
                
                # Bayes-kutistus (Shrinkage): jos otteluita on vähän, vedetään kohti nousijan/keskiarvon arvoja
                credibility = min(1.0, h_weight / 10.0) # 10 painotetun ottelun jälkeen luotetaan täysin
                self.home_attack[team] = credibility * raw_h_att + (1 - credibility) * self.PROMOTED_ATTACK
                self.home_defense[team] = credibility * raw_h_def + (1 - credibility) * self.PROMOTED_DEFENSE
            else:
                self.home_attack[team] = self.PROMOTED_ATTACK
                self.home_defense[team] = self.PROMOTED_DEFENSE

            # Vieraspelit
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
        # Haetaan parametrit (nousijoille käytetään automaattisesti regressoituja oletuksia)
        h_att = self.home_attack.get(home_team, self.PROMOTED_ATTACK)
        a_def = self.away_defense.get(away_team, self.PROMOTED_DEFENSE)
        a_att = self.away_attack.get(away_team, self.PROMOTED_ATTACK)
        h_def = self.home_defense.get(home_team, self.PROMOTED_DEFENSE)

        # Lasketaan maaliodottamat (lambda)
        lambda_home = h_att * a_def * self.league_avg_home_goals
        lambda_away = a_att * h_def * self.league_avg_away_goals

        # Poisson-jakaumat ja matriisi
        home_probs = poisson.pmf(np.arange(0, max_goals), lambda_home)
        away_probs = poisson.pmf(np.arange(0, max_goals), lambda_away)
        matrix = np.outer(home_probs, away_probs)

        # 1X2 Todennäköisyydet
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