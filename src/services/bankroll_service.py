from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo
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
        db: Session, portfolio: str = "poisson", initial_amount: float = 1000.00
    ) -> Bankroll:
        bankroll = db.query(Bankroll).filter(Bankroll.portfolio == portfolio).first()
        if not bankroll:
            bankroll = Bankroll(
                portfolio=portfolio,
                initial_balance=initial_amount,
                current_balance=initial_amount
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
        portfolio: str = "poisson",
    ) -> bool:
        existing = (
            db.query(PaperBet)
            .filter(
                PaperBet.match_id == match_id,
                PaperBet.market_type == market_type,
                PaperBet.outcome == outcome,
                PaperBet.portfolio == portfolio,
            )
            .first()
        )
        if existing:
            return False

        bankroll = BankrollService.get_or_create_bankroll(db, portfolio=portfolio)
        stake_eur = round(
            bankroll.current_balance * (stake_pct / 100.0), 2
        )
        if stake_eur < 1.0:
            return False

        bet = PaperBet(
            portfolio=portfolio,
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
    def settle_bets_for_match(db: Session, match_id: int, actual_home: int, actual_away: int, actual_cards: Optional[int] = None):
        pending_bets = db.query(PaperBet).filter(
            PaperBet.match_id == match_id,
            PaperBet.status == "PENDING"
        ).all()
        if not pending_bets:
            return

        actual_1x2 = "H" if actual_home > actual_away else ("D" if actual_home == actual_away else "A")

        # Cache bankrolls per portfolio during settlement
        bankrolls_by_portfolio = {}

        for bet in pending_bets:
            won = None  # None tarkoittaa, ettei ratkaisua voi vielä tehdä
            
            if bet.market_type == "1X2":
                won = (bet.outcome == actual_1x2)
            elif bet.market_type.startswith("CARDS_OVER_"):
                if actual_cards is not None:
                    line_str = bet.market_type.replace("CARDS_OVER_", "").replace("_", ".")
                    try:
                        line_val = float(line_str)
                        won = (actual_cards > line_val)
                    except ValueError:
                        won = False
                else:
                    # Jos korttidataa ei ole vielä saatavilla, ohitetaan ratkaisu ja jätetään avoimeksi!
                    continue

            # Ratkaistaan vain ne vedot, joista on varma tieto (True tai False)
            if won is not None:
                p_name = bet.portfolio or "poisson"
                if p_name not in bankrolls_by_portfolio:
                    bankrolls_by_portfolio[p_name] = BankrollService.get_or_create_bankroll(db, portfolio=p_name)
                b_roll = bankrolls_by_portfolio[p_name]

                if won:
                    bet.status = "WON"
                    bet.pnl = round(bet.stake_amount * (bet.odds - 1.0), 2)
                    bet.settled_at = datetime.now(timezone.utc)
                    b_roll.current_balance += bet.pnl
                elif not won:
                    bet.status = "LOST"
                    bet.pnl = -bet.stake_amount
                    bet.settled_at = datetime.now(timezone.utc)
                    b_roll.current_balance += bet.pnl

        db.commit()

    @staticmethod
    def get_portfolio_summary(db: Session, portfolio: str = "poisson") -> dict:
        bankroll = BankrollService.get_or_create_bankroll(db, portfolio=portfolio)
        
        # 1. Avoimet vedot, yhdistettynä Match-tauluun jotta saadaan päivämäärä
        pending_results = (
            db.query(PaperBet, Match.match_datetime)
            .join(Match, Match.match_id == PaperBet.match_id)
            .filter(PaperBet.status == "PENDING", PaperBet.portfolio == portfolio)
            .order_by(Match.match_datetime.asc())
            .all()
        )
        
        pending_bets = []
        for bet, m_date in pending_results:
            if m_date:
                dt_utc = m_date if m_date.tzinfo else m_date.replace(tzinfo=timezone.utc)
                bet.match_date_str = dt_utc.astimezone(ZoneInfo("Europe/Helsinki")).strftime("%d.%m. %H:%M")
            else:
                bet.match_date_str = "-"
            pending_bets.append(bet)
            
        # 2. Kaikki ratkaistut vedot ja niiden päivämäärät
        settled_results = (
            db.query(PaperBet, Match.match_datetime)
            .join(Match, Match.match_id == PaperBet.match_id)
            .filter(PaperBet.status.in_(["WON", "LOST"]), PaperBet.portfolio == portfolio)
            .all()
        )
        
        all_settled = []
        for bet, m_date in settled_results:
            if m_date:
                dt_utc = m_date if m_date.tzinfo else m_date.replace(tzinfo=timezone.utc)
                bet.match_date_str = dt_utc.astimezone(ZoneInfo("Europe/Helsinki")).strftime("%d.%m. %H:%M")
            else:
                bet.match_date_str = "-"
            all_settled.append(bet)
            
        # 3. Ratkaistujen vetojen historia UI:ta varten
        settled_history = sorted(
            all_settled, 
            key=lambda b: b.settled_at if b.settled_at else b.placed_at, 
            reverse=True
        )[:100]

        total_staked = sum(float(b.stake_amount) for b in all_settled)
        total_pnl = sum(float(b.pnl) for b in all_settled)
        total_won = sum(1 for b in all_settled if b.status == "WON")

        # Korjataan saldo laskennallisesti vetojen PnL-summasta,
        # jotta balance ei voi ajautua erilleen (esim. double-settle bugin jäljiltä).
        # Panoksia ei vähennetä sijoitushetkellä, joten oikea kaava on initial + pnl.
        correct_balance = round(bankroll.initial_balance + total_pnl, 2)
        if round(bankroll.current_balance, 2) != correct_balance:
            bankroll.current_balance = correct_balance
            db.commit()



        # Liigakohtainen ja mallikohtainen erittely
        leagues_breakdown = {}
        for code, cfg in LEAGUES_CONFIG.items():
            l_bets = [b for b in all_settled if b.league_code == code]
            
            bets_1x2 = [b for b in l_bets if b.market_type == "1X2"]
            bets_cards = [b for b in l_bets if b.market_type != "1X2"]

            def calc_stats(bet_list):
                stk = sum(float(b.stake_amount) for b in bet_list)
                pnl = sum(float(b.pnl) for b in bet_list)
                won = sum(1 for b in bet_list if b.status == "WON")
                roi = round(pnl / stk * 100, 1) if stk > 0 else 0.0
                win_rate = round(won / len(bet_list) * 100, 1) if bet_list else 0.0
                return len(bet_list), round(pnl, 2), roi, win_rate

            c_1x2, pnl_1x2, roi_1x2, wr_1x2 = calc_stats(bets_1x2)
            c_cards, pnl_cards, roi_cards, wr_cards = calc_stats(bets_cards)

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
                "1x2": {
                    "count": c_1x2,
                    "pnl": pnl_1x2,
                    "roi_pct": roi_1x2,
                    "win_rate": wr_1x2,
                    "brier_score": round(float(avg_brier), 4) if avg_brier is not None else "-"
                },
                "cards": {
                    "count": c_cards,
                    "pnl": pnl_cards,
                    "roi_pct": roi_cards,
                    "win_rate": wr_cards
                }
            }

        return {
            "portfolio": portfolio,
            "current_balance": round(bankroll.current_balance, 2),
            "initial_balance": round(bankroll.initial_balance, 2),
            "total_pnl": round(total_pnl, 2),
            "total_roi_pct": (
                round(total_pnl / bankroll.initial_balance * 100, 1)
                if bankroll.initial_balance > 0
                else 0.0
            ),
            "total_win_rate": (
                round(total_won / len(all_settled) * 100, 1) if all_settled else 0.0
            ),
            "leagues_breakdown": leagues_breakdown,
            "settled_bets_count": len(all_settled),
            "pending_bets_count": len(pending_bets),
            "pending_bets": pending_bets,
            "settled_history": settled_history,
        }