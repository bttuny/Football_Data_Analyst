import numpy as np

def calculate_brier_score(prob_home: float, prob_draw: float, prob_away: float, actual_home_goals: int, actual_away_goals: int) -> float:
    """Calculate the Brier score for 1x2 predictions.
    Value 0.0 means perfect prediction, 2.0 means worst prediction.
    """

    if actual_home_goals > actual_away_goals:
        actual_outcome = np.array([1.0, 0.0, 0.0])  # Home win
    elif actual_home_goals == actual_away_goals:
        actual_outcome = np.array([0.0, 1.0, 0.0])  # Draw
    else:
        actual_outcome = np.array([0.0, 0.0, 1.0])  # Away win

    predicted_probs = np.array([prob_home, prob_draw, prob_away])

    brier = float(np.sum((np.array(predicted_probs) - np.array(actual_outcome)) ** 2))
    return round(brier, 4)

def calculate_log_loss(prob_home: float, prob_draw: float, prob_away: float, actual_home_goals: int, actual_away_goals: int, eps: float = 1e-15) -> float:
    """Calculate the log loss for predictions.
    Punishes confident but wrong predictions more heavily.
    """

    if actual_home_goals > actual_away_goals:
       p_actual = prob_home
    elif actual_home_goals == actual_away_goals:
        p_actual = prob_draw
    else:
        p_actual = prob_away

    # Avoid log(0) by clipping the probability
    p_actual = max(eps, min(1 - eps, p_actual))

    log_loss = -np.log(p_actual)
    return round(float(log_loss), 4)