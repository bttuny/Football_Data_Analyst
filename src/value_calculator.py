# src/value_calculator.py
from typing import Dict, Any, List

def calculate_value_bets(prob_home: float, prob_draw: float, prob_away: float, 
                         odds_home: float, odds_draw: float, odds_away: float) -> List[Dict[str, Any]]:
    """
    Laskee odotusarvon (EV) ja 1/4 Kelly -panoksen kaikille kolmelle merkille.
    """
    outcomes = [
        ("H", prob_home, odds_home, "Kotivoitto"),
        ("D", prob_draw, odds_draw, "Tasapeli"),
        ("A", prob_away, odds_away, "Vierasvoitto")
    ]

    value_bets = []

    for code, prob, odds, label in outcomes:
        if odds <= 1.0 or prob <= 0:
            continue

        # EV = (Prob * Odds) - 1
        ev = (prob * odds) - 1.0
        
        # 1/4 Kelly Stake %
        b = odds - 1.0
        kelly_full = (b * prob - (1.0 - prob)) / b if b > 0 else 0
        kelly_quarter = max(0.0, kelly_full * 0.25)

        is_value = ev > 0.02  # Yli 2% ylikerroin kynnyksenä

        value_bets.append({
            "outcome": code,
            "label": label,
            "prob": round(prob, 4),
            "odds": odds,
            "fair_odds": round(1 / prob, 2) if prob > 0 else 0,
            "ev_percentage": round(ev * 100, 2),
            "kelly_stake_pct": round(kelly_quarter * 100, 2),
            "is_value": is_value
        })

    return value_bets