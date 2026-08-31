from datetime import datetime, timezone
from typing import Optional, Any
from sqlalchemy import Integer, String, Numeric, DateTime, ForeignKey, Boolean, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship, Mapped, mapped_column
from src.core.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class League(Base):
    __tablename__ = "leagues"

    league_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # esim. 'PL', 'PD', 'SA'
    country: Mapped[str] = mapped_column(String(100), nullable=False)


class Match(Base):
    __tablename__ = "matches"

    match_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    league_id: Mapped[int] = mapped_column(Integer, ForeignKey("leagues.league_id"), nullable=False)
    season: Mapped[str] = mapped_column(String(20), nullable=False)
    home_team: Mapped[str] = mapped_column(String(100), nullable=False)
    away_team: Mapped[str] = mapped_column(String(100), nullable=False)
    match_datetime: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    referee: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="SCHEDULED")
    actual_home_goals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    actual_away_goals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    league: Mapped[Optional[League]] = relationship("League")


class MatchPrediction(Base):
    __tablename__ = "match_predictions"

    prediction_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.match_id"), nullable=False)
    predicted_home_xg: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    predicted_away_xg: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    prob_home_win: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    prob_draw: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    prob_away_win: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PredictionEvaluation(Base):
    __tablename__ = "prediction_evaluations"

    evaluation_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.match_id"), nullable=False)
    prediction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("match_predictions.prediction_id"), nullable=False
    )
    brier_score: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    log_loss: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    outcome_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --- PAPER TRADING / BANKROLL MODELS ---


class Bankroll(Base):
    __tablename__ = "bankrolls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    portfolio: Mapped[str] = mapped_column(String(30), default="poisson", index=True)  # 'poisson' tai 'neg_binom'
    initial_balance: Mapped[float] = mapped_column(Numeric(10, 2), default=1000.00)
    current_balance: Mapped[float] = mapped_column(Numeric(10, 2), default=1000.00)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PaperBet(Base):
    __tablename__ = "paper_bets"

    bet_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    portfolio: Mapped[str] = mapped_column(String(30), default="poisson", index=True)  # 'poisson' tai 'neg_binom'
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.match_id"), nullable=False)
    league_code: Mapped[str] = mapped_column(String(20), default="PL")
    match_name: Mapped[str] = mapped_column(String(150), nullable=False)
    market_type: Mapped[str] = mapped_column(String(30), default="1X2")  # '1X2' tai 'CARDS_OVER_3_5'
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)      # 'H', 'D', 'A', 'OVER_3_5'
    odds: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    ev_percentage: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    stake_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    stake_percentage: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")    # 'PENDING', 'WON', 'LOST', 'VOID'
    pnl: Mapped[float] = mapped_column(Numeric(10, 2), default=0.00)
    placed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    settled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, default="user", nullable=False) 


class OddsCache(Base):
    __tablename__ = "odds_cache"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    sport_key: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True)
    data: Mapped[Optional[Any]] = mapped_column(JSON) # Tähän tallennetaan API:n palauttamat kertoimet
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), default=func.now())


class CardsModelCache(Base):
    __tablename__ = "cards_model_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    league_code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    league_avg_cards: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, default=4.4)
    dispersion_alpha: Mapped[Optional[float]] = mapped_column(Numeric(6, 4), nullable=True, default=0.08)
    team_card_factors: Mapped[Optional[Any]] = mapped_column(JSON)   # {"arsenal": 1.12, "chelsea": 0.95, ...}
    referee_factors: Mapped[Optional[Any]] = mapped_column(JSON)     # {"michael oliver": 1.15, ...}
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=func.now(), onupdate=func.now())