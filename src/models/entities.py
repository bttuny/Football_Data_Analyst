from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from src.core.database import Base

class League(Base):
    __tablename__ = "leagues"

    league_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(20), unique=True, nullable=False)  # esim. 'PL', 'PD', 'SA'
    country = Column(String(100), nullable=False)


class Match(Base):
    __tablename__ = "matches"

    match_id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("leagues.league_id"), nullable=False)
    season = Column(String(20), nullable=False)
    home_team = Column(String(100), nullable=False)
    away_team = Column(String(100), nullable=False)
    match_datetime = Column(DateTime, nullable=False)
    referee = Column(String(100), nullable=True)
    status = Column(String(20), default="SCHEDULED")
    actual_home_goals = Column(Integer, nullable=True)
    actual_away_goals = Column(Integer, nullable=True)

    league = relationship("League")


class MatchPrediction(Base):
    __tablename__ = "match_predictions"

    prediction_id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.match_id"), nullable=False)
    predicted_home_xg = Column(Numeric(4, 2), nullable=False)
    predicted_away_xg = Column(Numeric(4, 2), nullable=False)
    prob_home_win = Column(Numeric(5, 4), nullable=False)
    prob_draw = Column(Numeric(5, 4), nullable=False)
    prob_away_win = Column(Numeric(5, 4), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PredictionEvaluation(Base):
    __tablename__ = "prediction_evaluations"

    evaluation_id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.match_id"), nullable=False)
    prediction_id = Column(
        Integer, ForeignKey("match_predictions.prediction_id"), nullable=False
    )
    brier_score = Column(Numeric(6, 4), nullable=False)
    log_loss = Column(Numeric(6, 4), nullable=False)
    outcome_correct = Column(Boolean, nullable=False)
    evaluated_at = Column(DateTime, default=datetime.utcnow)


# --- PAPER TRADING / BANKROLL MODELS ---


class Bankroll(Base):
    __tablename__ = "bankrolls"

    id = Column(Integer, primary_key=True, index=True)
    initial_balance = Column(Numeric(10, 2), default=1000.00)
    current_balance = Column(Numeric(10, 2), default=1000.00)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaperBet(Base):
    __tablename__ = "paper_bets"

    bet_id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.match_id"), nullable=False)
    league_code = Column(String(20), default="PL")
    match_name = Column(String(150), nullable=False)
    market_type = Column(String(30), default="1X2")  # '1X2' tai 'CARDS_OVER_3_5'
    outcome = Column(String(20), nullable=False)      # 'H', 'D', 'A', 'OVER_3_5'
    odds = Column(Numeric(6, 2), nullable=False)
    ev_percentage = Column(Numeric(6, 2), nullable=False)
    stake_amount = Column(Numeric(10, 2), nullable=False)
    stake_percentage = Column(Numeric(5, 2), nullable=False)
    status = Column(String(20), default="PENDING")    # 'PENDING', 'WON', 'LOST', 'VOID'
    pnl = Column(Numeric(10, 2), default=0.00)
    placed_at = Column(DateTime, default=datetime.utcnow)
    settled_at = Column(DateTime, nullable=True)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user", nullable=False) 