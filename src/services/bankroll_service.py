# src/services/bankroll_service.py
from datetime import datetime
from sqlalchemy.orm import Session
from src.models.entities import Bankroll, PaperBet


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
        market_type: str = "1X2",
    ) -> bool:
        """Tallentaa vedon kantaan."""
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
    def settle_bets_for_match(
        db: Session,
        match_id: int,
        actual_home: int,
        actual_away: int,
        actual_cards: int = None,
    ):
        """Ratkaisee sekä 1X2- että korttivedot."""
        pending_bets = (
            db.query(PaperBet)
            .filter(PaperBet.match_id == match_id, PaperBet.status == "PENDING")
            .all()
        )
        if not pending_bets:
            return

        bankroll = BankrollService.get_or_create_bankroll(db)

        # 1X2 voittaja
        actual_1x2 = (
            "H"
            if actual_home > actual_away
            else ("D" if actual_home == actual_away else "A")
        )

        for bet in pending_bets:
            bet.settled_at = datetime.utcnow()
            won = False

            if bet.market_type == "1X2":
                won = bet.outcome == actual_1x2
            elif bet.market_type == "CARDS_OVER_3_5" and actual_cards is not None:
                won = actual_cards > 3.5

            if won:
                bet.status = "WON"
                bet.pnl = round(
                    float(bet.stake_amount) * (float(bet.odds) - 1.0), 2
                )
                bankroll.current_balance = float(bankroll.current_balance) + bet.pnl
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
        won_count = sum(1 for b in settled if b.status == "WON")

        # Eritellään 1X2 ja Kortit
        cards_settled = [b for b in settled if b.market_type == "CARDS_OVER_3_5"]
        cards_pnl = sum(float(b.pnl) for b in cards_settled)

        return {
            "current_balance": round(float(bankroll.current_balance), 2),
            "initial_balance": round(float(bankroll.initial_balance), 2),
            "total_pnl": round(total_pnl, 2),
            "cards_pnl": round(cards_pnl, 2),
            "roi_pct": (
                round(total_pnl / total_staked * 100, 1)
                if total_staked > 0
                else 0.0
            ),
            "win_rate_pct": (
                round(won_count / len(settled) * 100, 1) if settled else 0.0
            ),
            "settled_bets_count": len(settled),
            "pending_bets_count": sum(
                1 for b in bets if b.status == "PENDING"
            ),
            "recent_bets": bets,
        }