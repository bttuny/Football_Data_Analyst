from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy import create_engine, Column, Integer, String, Numeric, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from config.settings import DATABASE_URL

# Create the SQLAlchemy engine
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class League(Base):
    __tablename__ = "leagues"

    league_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)
    country = Column(String(50), nullable=False)
    code = Column(String(10), unique=True, nullable=False)

class Team(Base):
    __tablename__ = "teams"

    team_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    short_code = Column(String(10), nullable=False)


class Match(Base):
    __tablename__ = "matches"

    match_id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.league_id"), nullable=False)
    season = Column(String(9), nullable=False)
    home_team = Column(String(100), nullable=False)
    away_team = Column(String(100), nullable=False)
    match_datetime = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), default="SCHEDULED")

    actual_home_goals = Column(Integer, nullable=True)
    actual_away_goals = Column(Integer, nullable=True)
    actual_home_xg = Column(Numeric(4, 2), nullable=True)
    actual_away_xg = Column(Numeric(4, 2), nullable=True)

    prections = relationship("MatchPrediction", back_populates="match")

class MatchPrediction(Base):
    __tablename__ = "match_predictions_history"

    prediction_id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.match_id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    model_version = Column(String(20), nullable=False, default="1.0.0")

    predicted_home_xg = Column(Numeric(4, 2), nullable=False)
    predicted_away_xg = Column(Numeric(4, 2), nullable=False)
    prob_draw = Column(Numeric(5, 4), nullable=False)
    prob_home_win = Column(Numeric(5, 4), nullable=False)
    prob_away_win = Column(Numeric(5, 4), nullable=False)

    match = relationship("Match", back_populates="prections")


def init_db():
    """
    Initializes the database by creating all tables.
    """
    Base.metadata.create_all(bind=engine)
    print("Database initialized and tables created.")

def save_prediction(prediction_data: Dict[str, Any], match_id: int):
    """
    Saves the prediction data to the database.
    """
    session = SessionLocal()
    try:
        prediction = MatchPrediction(
            match_id=match_id,
            predicted_home_xg=prediction_data['expected_goals_home'],
            predicted_away_xg=prediction_data['expected_goals_away'],
            prob_draw=prediction_data['prob_draw'],
            prob_home_win=prediction_data['prob_home_win'],
            prob_away_win=prediction_data['prob_away_win'],
            model_version="1.0.0"
        )
        session.add(prediction)

        #Update the match status to LOCKED after saving the prediction
        match = session.query(Match).filter(Match.match_id == match_id).first()
        if match:
            match.status = "LOCKED"

        session.commit()
        print(f"Prediction for match_id {match_id} saved successfully.")
    except Exception as e:
        session.rollback()
        print(f"Error saving prediction for match_id {match_id}: {e}")
        raise
    finally:
        session.close()