# src/value_calculator.py
from typing import Dict, Any, List

def calculate_value_bets(prob_home: float, prob_draw: float, prob_away: float, 
                         odds_home: float, odds_draw: float, odds_away: float) -> List[Dict[str, Any]]:
    outcomes = [
        ("H", prob_home, odds_home, "Kotivoitto"),
        ("D", prob_draw, odds_draw, "Tasapeli"),
        ("A", prob_away, odds_away, "Vierasvoitto")
    ]

    value_bets = []

    for code, prob, odds, label in outcomes:
        if odds <= 1.0 or prob <= 0:
            value_bets.append({
                "outcome": code, "label": label, "prob": prob, "odds": odds,
                "fair_odds": 0, "ev_percentage": 0, "kelly_stake_pct": 0, "is_value": False
            })
            continue

        ev = (prob * odds) - 1.0
        
        # Kelly-peruslaskenta
        b = odds - 1.0
        kelly_full = (b * prob - (1.0 - prob)) / b if b > 0 else 0

        # VARIASSIN HALLINTA:
        # Pienennetään panosmurto-osaa mitä korkeampi kerroin on (Longshot-riski)
        if odds > 4.50:
            fraction = 0.10  # 1/10 Kelly jättikertoimille
            max_cap = 0.6    # Max 0.6% kassan panos
        elif odds > 2.50:
            fraction = 0.15  # n. 1/7 Kelly
            max_cap = 1.5    # Max 1.5% kassan panos
        else:
            fraction = 0.25  # 1/4 Kelly matalille kertoimille
            max_cap = 2.5    # Max 2.5% kassan panos

        kelly_stake = max(0.0, kelly_full * fraction)
        recommended_stake = min(max_cap, round(kelly_stake * 100, 1))

        # Ylikerroin vain jos EV > 3%
        is_value = (ev > 0.03) and (recommended_stake > 0.1)

        value_bets.append({
            "outcome": code,
            "label": label,
            "prob": round(prob, 4),
            "odds": odds,
            "fair_odds": round(1 / prob, 2) if prob > 0 else 0,
            "ev_percentage": round(ev * 100, 1),
            "kelly_stake_pct": recommended_stake,
            "is_value": is_value
        })

    return value_bets