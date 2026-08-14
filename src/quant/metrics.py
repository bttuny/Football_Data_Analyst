import numpy as np

def calculate_brier_score(
    prob_h: float, prob_d: float, prob_a: float, home_goals: int, away_goals: int
) -> float:
    actual = [
        1 if home_goals > away_goals else 0,
        1 if home_goals == away_goals else 0,
        1 if home_goals < away_goals else 0,
    ]
    probs = [prob_h, prob_d, prob_a]
    return float(round(np.mean([(p - o) ** 2 for p, o in zip(probs, actual)]), 4))


def calculate_log_loss(
    prob_h: float, prob_d: float, prob_a: float, home_goals: int, away_goals: int
) -> float:
    actual = [
        1 if home_goals > away_goals else 0,
        1 if home_goals == away_goals else 0,
        1 if home_goals < away_goals else 0,
    ]
    probs = [max(1e-5, min(1 - 1e-5, p)) for p in [prob_h, prob_d, prob_a]]
    return float(round(-np.sum([o * np.log(p) for p, o in zip(probs, actual)]), 4))