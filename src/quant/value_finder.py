from typing import Dict, Any, List

def calculate_value_bets(
    prob_home: float,
    prob_draw: float,
    prob_away: float,
    odds_home: float,
    odds_draw: float,
    odds_away: float,
) -> List[Dict[str, Any]]:
    # SQLAlchemy Numeric -sarakkeet palauttavat decimal.Decimal-olioita,
    # jotka eivät toimi suoraan float-laskuissa -> muunnetaan varmuuden vuoksi
    outcomes = [
        ("H", float(prob_home), float(odds_home), "Kotivoitto"),
        ("D", float(prob_draw), float(odds_draw), "Tasapeli"),
        ("A", float(prob_away), float(odds_away), "Vierasvoitto"),
    ]
    results = []

    for code, prob, odds, label in outcomes:
        if odds <= 1.0 or prob <= 0:
            results.append({
                "outcome": code,
                "label": label,
                "prob": prob,
                "odds": odds,
                "fair_odds": 0,
                "ev_percentage": 0,
                "kelly_stake_pct": 0,
                "is_value": False,
            })
            continue

        ev = (prob * odds) - 1.0
        b = odds - 1.0
        kelly_full = (b * prob - (1.0 - prob)) / b if b > 0 else 0

        # Varianssikertoimet
        if odds > 4.50:
            fraction, max_cap = 0.10, 0.6
        elif odds > 2.50:
            fraction, max_cap = 0.15, 1.5
        else:
            fraction, max_cap = 0.25, 2.5

        stake = min(max_cap, round(max(0.0, kelly_full * fraction) * 100, 1))
        is_val = (ev > 0.03) and (stake >= 0.1)

        results.append({
            "outcome": code,
            "label": label,
            "prob": round(prob, 4),
            "odds": odds,
            "fair_odds": round(1 / prob, 2) if prob > 0 else 0,
            "ev_percentage": round(ev * 100, 1),
            "kelly_stake_pct": stake,
            "is_value": is_val,
        })
    return results