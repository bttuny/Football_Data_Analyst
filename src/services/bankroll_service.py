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
    ) -> bool:
        """Asettaa automaattisen Kelly-vedon, jos sitä ei ole vielä asetettu."""
        existing = (
            db.query(PaperBet)
            .filter(PaperBet.match_id == match_id, PaperBet.outcome == outcome)
            .first()
        )
        if existing:
            return False

        bankroll = BankrollService.get_or_create_bankroll(db)
        stake_eur = round(float(bankroll.current_balance) * (stake_pct / 100.0), 2)

        if stake_eur < 1.0:
            return False

        bet = PaperBet(
            match_id=match_id,
            match_name=match_name,
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
        db: Session, match_id: int, actual_home: int, actual_away: int
    ):
        """Ratkaisee otteluun liittyvät avoimet vedot ja päivittää kassan."""
        pending_bets = (
            db.query(PaperBet)
            .filter(PaperBet.match_id == match_id, PaperBet.status == "PENDING")
            .all()
        )
        if not pending_bets:
            return

        actual_outcome = (
            "H"
            if actual_home > actual_away
            else ("D" if actual_home == actual_away else "A")
        )
        bankroll = BankrollService.get_or_create_bankroll(db)

        for bet in pending_bets:
            bet.settled_at = datetime.utcnow()
            if bet.outcome == actual_outcome:
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
        """Laskee Paper Trading -tilastot dashboardia varten."""
        bankroll = BankrollService.get_or_create_bankroll(db)
        bets = (
            db.query(PaperBet).order_by(PaperBet.placed_at.desc()).limit(50).all()
        )

        settled = [b for b in bets if b.status in ["WON", "LOST"]]
        total_staked = sum(float(b.stake_amount) for b in settled)
        total_pnl = sum(float(b.pnl) for b in settled)
        won_count = sum(1 for b in settled if b.status == "WON")

        roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0.0
        win_rate = (won_count / len(settled) * 100) if settled else 0.0

        return {
            "current_balance": round(float(bankroll.current_balance), 2),
            "initial_balance": round(float(bankroll.initial_balance), 2),
            "total_pnl": round(total_pnl, 2),
            "roi_pct": round(roi, 1),
            "win_rate_pct": round(win_rate, 1),
            "settled_bets_count": len(settled),
            "pending_bets_count": sum(
                1 for b in bets if b.status == "PENDING"
            ),
            "recent_bets": bets,
        }