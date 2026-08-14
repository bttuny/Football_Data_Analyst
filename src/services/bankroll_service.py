# src/services/bankroll_service.py
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.core.config import LEAGUES_CONFIG
from src.models.entities import (
    Bankroll,
    PaperBet,
    PredictionEvaluation,
    Match,
    League,
)


class BankrollService:

    @staticmethod
    def get_or_create_bankroll(
        db: Session, initial_amount: float = 1000.00
    ) -> Bankroll:
        bankroll = db.query(Bankroll).first()
        if not bankroll:
            bankroll = Bankroll(
                initial_balance=initial_amount, current_balance=initial_amount
            )
            db.add(bankroll)
            db.commit()
            db.refresh(bankroll)
        return bankroll

    @staticmethod
    def place_value_bet(
        db: Session,
        match_id: int,
        match_name: str,
        outcome: str,
        odds: float,
        ev_pct: float,
        stake_pct: float,
        league_code: str = "PL",
        market_type: str = "1X2",
    ) -> bool:
        existing = (
            db.query(PaperBet)
            .filter(
                PaperBet.match_id == match_id,
                PaperBet.market_type == market_type,
                PaperBet.outcome == outcome,
            )
            .first()
        )
        if existing:
            return False

        bankroll = BankrollService.get_or_create_bankroll(db)
        stake_eur = round(
            float(bankroll.current_balance) * (stake_pct / 100.0), 2
        )
        if stake_eur < 1.0:
            return False

        bet = PaperBet(
            match_id=match_id,
            league_code=league_code,
            match_name=match_name,
            market_type=market_type,
            outcome=outcome,
            odds=odds,
            ev_percentage=ev_pct,
            stake_amount=stake_eur,
            stake_percentage=stake_pct,
            status="PENDING",
            pnl=0.00,
        )
        db.add(bet)
        db.commit()
        return True

    @staticmethod
    def settle_bets_for_match(db: Session, match_id: int, actual_home: int, actual_away: int, actual_cards: int = None):
        pending_bets = db.query(PaperBet).filter(
            PaperBet.match_id == match_id,
            PaperBet.status == "PENDING"
        ).all()
        if not pending_bets:
            return

        bankroll = BankrollService.get_or_create_bankroll(db)
        actual_1x2 = "H" if actual_home > actual_away else ("D" if actual_home == actual_away else "A")

        for bet in pending_bets:
            bet.settled_at = datetime.utcnow()
            won = False
            if bet.market_type == "1X2":
                won = (bet.outcome == actual_1x2)
            elif bet.market_type.startswith("CARDS_OVER_") and actual_cards is not None:
                # Erotetaan linja, esim. CARDS_OVER_4_5 -> 4.5
                line_str = bet.market_type.replace("CARDS_OVER_", "").replace("_", ".")
                try:
                    line_val = float(line_str)
                    won = (actual_cards > line_val)
                except ValueError:
                    won = False

            if won:
                bet.status = "WON"
                bet.pnl = round(float(bet.stake_amount) * (float(bet.odds) - 1.0), 2)
            else:
                bet.status = "LOST"
                bet.pnl = -float(bet.stake_amount)

            bankroll.current_balance = float(bankroll.current_balance) + bet.pnl

        db.commit()

    @staticmethod
    def get_portfolio_summary(db: Session) -> dict:
        bankroll = BankrollService.get_or_create_bankroll(db)
        bets = (
            db.query(PaperBet)
            .order_by(PaperBet.placed_at.desc())
            .limit(100)
            .all()
        )
        settled = [b for b in bets if b.status in ["WON", "LOST"]]

        total_staked = sum(float(b.stake_amount) for b in settled)
        total_pnl = sum(float(b.pnl) for b in settled)
        total_won = sum(1 for b in settled if b.status == "WON")

        # Liigakohtainen erittely
        leagues_breakdown = {}
        for code, cfg in LEAGUES_CONFIG.items():
            l_bets = [b for b in settled if b.league_code == code]
            l_staked = sum(float(b.stake_amount) for b in l_bets)
            l_pnl = sum(float(b.pnl) for b in l_bets)
            l_won = sum(1 for b in l_bets if b.status == "WON")

            # Haetaan liigan 1X2 Brier Score
            avg_brier = (
                db.query(func.avg(PredictionEvaluation.brier_score))
                .join(Match, Match.match_id == PredictionEvaluation.match_id)
                .join(League, League.league_id == Match.league_id)
                .filter(League.code == code)
                .scalar()
            )

            leagues_breakdown[code] = {
                "name": cfg["name"],
                "badge_color": cfg["badge_color"],
                "count": len(l_bets),
                "pnl": round(l_pnl, 2),
                "roi_pct": (
                    round(l_pnl / l_staked * 100, 1) if l_staked > 0 else 0.0
                ),
                "win_rate": (
                    round(l_won / len(l_bets) * 100, 1) if l_bets else 0.0
                ),
                "brier_score": (
                    round(float(avg_brier), 4) if avg_brier is not None else "-"
                ),
            }

        return {
            "current_balance": round(float(bankroll.current_balance), 2),
            "initial_balance": round(float(bankroll.initial_balance), 2),
            "total_pnl": round(total_pnl, 2),
            "total_roi_pct": (
                round(total_pnl / total_staked * 100, 1)
                if total_staked > 0
                else 0.0
            ),
            "total_win_rate": (
                round(total_won / len(settled) * 100, 1) if settled else 0.0
            ),
            "leagues_breakdown": leagues_breakdown,
            "settled_bets_count": len(settled),
            "pending_bets_count": sum(
                1 for b in bets if b.status == "PENDING"
            ),
            "recent_bets": bets,
        }