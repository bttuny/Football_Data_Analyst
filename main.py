# main.py
from datetime import datetime, timezone
import pandas as pd
from sqlalchemy.exc import IntegrityError

from src.core.config import LEAGUES_CONFIG
from src.core.database import SessionLocal, Base, engine
from src.models.entities import (
    League,
    Match,
    MatchPrediction,
    PredictionEvaluation,
    CardsModelCache,
    OddsCache,
)
from src.ingestion.football_data import FootballDataFetcher
from src.ingestion.historical_data import CardsDataFetcher
from src.ingestion.odds_fetcher import OddsFetcher
from src.quant.poisson_dixon import PremierLeaguePoissonModel
from src.quant.metrics import calculate_brier_score, calculate_log_loss
from src.quant.cards_model import PremierLeagueCardsModel, clean_name
from src.quant.value_finder import calculate_value_bets
from src.quant.xgb_value_bets import get_xgb_value_analysis
from src.services.bankroll_service import BankrollService


def run_pipeline():
    print("=== TOP 5 LEAGUES QUANT ANALYST & BANKROLL PIPELINE ===")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    fetcher = FootballDataFetcher()
    cards_fetcher = CardsDataFetcher()
    odds_fetcher = OddsFetcher()

    for code, conf in LEAGUES_CONFIG.items():
        print(f"\n--- Käsitellään {conf['name']} ({code}) ---")

        # 1. Lataa ja tallenna kortti- ja tuomaridata
        print("Ladataan kortti- ja tuomaridata...")
        cards_df = cards_fetcher.fetch_cards_history(league_csv=conf["csv_code"])
        if not cards_df.empty:
            # Vältetään fragmentaatiovaroitus .assign() metodilla
            cards_df = cards_df.assign(
                HomeClean=cards_df["HomeTeam"].apply(clean_name),
                AwayClean=cards_df["AwayTeam"].apply(clean_name)
            )
            print(f"✅ Korttidata ({len(cards_df)} ottelua) ladattu.")

            # Opetetaan korttimalli ja tallennetaan parametrit tietokantaan
            cards_model = PremierLeagueCardsModel()
            cards_model.fit(cards_df)

            cache = db.query(CardsModelCache).filter(CardsModelCache.league_code == code).first()
            if cache:
                cache.league_avg_cards = cards_model.league_avg_cards
                cache.dispersion_alpha = cards_model.dispersion_alpha
                cache.team_card_factors = cards_model.team_card_factors
                cache.referee_factors = {k: float(v) for k, v in cards_model.referee_factors.items()}
                cache.updated_at = datetime.now(timezone.utc)
            else:
                cache = CardsModelCache(
                    league_code=code,
                    league_avg_cards=cards_model.league_avg_cards,
                    dispersion_alpha=cards_model.dispersion_alpha,
                    team_card_factors=cards_model.team_card_factors,
                    referee_factors={k: float(v) for k, v in cards_model.referee_factors.items()},
                )
                db.add(cache)
            db.commit()
            print(f"💾 Korttimalli {code} tallennettu tietokantaan.")

        # 2. Varmistetaan liiga
        league_obj = db.query(League).filter(League.code == code).first()
        if not league_obj:
            league_obj = League(
                name=conf["name"], code=code, country=conf["country"]
            )
            db.add(league_obj)
            db.commit()
            db.refresh(league_obj)

        # 3. Haetaan data Dixon-Colesia varten
        df_prev, _ = fetcher.fetch_matches(
            competition_code=conf["football_data_code"], season=2025
        )
        df_curr, upcoming = fetcher.fetch_matches(
            competition_code=conf["football_data_code"], season=2026
        )

        # 4. Ratkaistaan pelatut pelit ja evaluoidaan
        locked_matches = (
            db.query(Match)
            .filter(
                Match.league_id == league_obj.league_id, Match.status == "LOCKED"
            )
            .all()
        )
        
        if not df_curr.empty and locked_matches:
            for match in locked_matches:
                m_data = df_curr[
                    (df_curr["home_team"] == match.home_team)
                    & (df_curr["away_team"] == match.away_team)
                ]
                if not m_data.empty:
                    row = m_data.iloc[0]
                    act_h, act_a = int(row["home_goals"]), int(row["away_goals"])
                    match.actual_home_goals = act_h
                    match.actual_away_goals = act_a
                    match.status = "FINISHED"

                    act_cards = None
                    if not cards_df.empty and "Date" in cards_df.columns:
                        c_match = cards_df[
                            (cards_df["HomeClean"] == clean_name(match.home_team)) &
                            (cards_df["AwayClean"] == clean_name(match.away_team))
                        ].copy()
                        if isinstance(c_match, pd.DataFrame) and not c_match.empty:
                            c_match["parsed_date"] = pd.to_datetime(c_match["Date"], dayfirst=True, errors="coerce")
                            c_match = c_match.sort_values(by="parsed_date")
                            last_match = c_match.iloc[-1]
                            
                            # Varmistetaan, ettei oteta viime kauden tulosta (max 4 päivän heitto ottelupäivästä)
                            if pd.notna(last_match["parsed_date"]) and match.match_datetime:
                                m_date = match.match_datetime.replace(tzinfo=None)
                                diff_days = abs((last_match["parsed_date"] - m_date).days)
                                if diff_days <= 4:
                                    act_cards = int(last_match["total_cards"])

                    # Ratkaistaan vedot salkussa
                    BankrollService.settle_bets_for_match(
                        db, match.match_id, act_h, act_a, actual_cards=act_cards
                    )

                    pred = (
                        db.query(MatchPrediction)
                        .filter(MatchPrediction.match_id == match.match_id)
                        .order_by(MatchPrediction.created_at.desc())
                        .first()
                    )
                    
                    if pred:
                        try:
                            # Varmistetaan, ettei evaluointia lisätä kahdesti
                            existing_eval = db.query(PredictionEvaluation).filter(PredictionEvaluation.match_id == match.match_id).first()
                            if not existing_eval:
                                brier = calculate_brier_score(
                                    pred.prob_home_win, pred.prob_draw, pred.prob_away_win,
                                    act_h, act_a,
                                )
                                loss = calculate_log_loss(
                                    pred.prob_home_win, pred.prob_draw, pred.prob_away_win,
                                    act_h, act_a,
                                )
                                pred_out = (
                                    "H" if pred.prob_home_win > max(pred.prob_draw, pred.prob_away_win)
                                    else ("D" if pred.prob_draw > pred.prob_away_win else "A")
                                )
                                act_out = "H" if act_h > act_a else ("D" if act_h == act_a else "A")

                                eval_obj = PredictionEvaluation(
                                    match_id=match.match_id,
                                    prediction_id=pred.prediction_id,
                                    brier_score=brier,
                                    log_loss=loss,
                                    outcome_correct=(pred_out == act_out),
                                )
                                db.add(eval_obj)
                                db.commit()
                        except Exception as e:
                            # DB Virhetilanteessa perutaan transaktio, jottei koko skripti kaadu
                            db.rollback()
                            print(f"  ⚠️ Ohitetaan evaluaation tallennus (tietokantavirhe ottelulle {match.match_id})")
            
            db.commit()

        # 5. Koulutetaan sarjakohtainen Dixon-Coles
        training_data = pd.concat([df_prev, df_curr], ignore_index=True)
        model = PremierLeaguePoissonModel()
        model.fit(training_data)

        # 6. Ennustetaan tulevat
        for m_data in upcoming:
            h, a = m_data["home_team"], m_data["away_team"]
            match_obj = (
                db.query(Match)
                .filter(
                    Match.home_team == h,
                    Match.away_team == a,
                    Match.league_id == league_obj.league_id,
                )
                .first()
            )
            if not match_obj:
                match_obj = Match(
                    league_id=league_obj.league_id,
                    season="2026/2027",
                    home_team=h,
                    away_team=a,
                    match_datetime=datetime.fromisoformat(
                        m_data["datetime"].replace("Z", "+00:00")
                    ),
                    referee=m_data.get("referee"),
                    status="SCHEDULED",
                )
                db.add(match_obj)
                db.commit()
                db.refresh(match_obj)
            else:
                if m_data.get("referee") and match_obj.referee != m_data.get("referee"):
                    match_obj.referee = m_data.get("referee")
                    db.commit()

            if match_obj.status in ["SCHEDULED", "LOCKED"]:
                pred = model.predict_match(h, a)
                new_pred = MatchPrediction(
                    match_id=match_obj.match_id,
                    predicted_home_xg=pred["expected_goals_home"],
                    predicted_away_xg=pred["expected_goals_away"],
                    prob_home_win=pred["prob_home_win"],
                    prob_draw=pred["prob_draw"],
                    prob_away_win=pred["prob_away_win"],
                )
                db.add(new_pred)
                match_obj.status = "LOCKED"
                db.commit()

        # 7. Kertoimet ja automaattinen arvovetojen asettaminen (Dixon-Coles & XGBoost)
        sport_key = conf.get("odds_key", "")
        events_list = []
        if sport_key:
            print(f"Haetaan kertoimet ja arvovedot liigalle {code}...")
            try:
                fetched_data = odds_fetcher.fetch_current_odds(sport_key=sport_key)
                if fetched_data:
                    events_list = fetched_data
                    cache_entry = db.query(OddsCache).filter(OddsCache.sport_key == sport_key).first()
                    if cache_entry:
                        cache_entry.data = events_list
                        cache_entry.updated_at = datetime.now(timezone.utc)
                    else:
                        db.add(OddsCache(sport_key=sport_key, data=events_list))
                    db.commit()
            except Exception as e:
                print(f"  ⚠️ Kertoimien haku epäonnistui ({sport_key}): {e}")

            if not events_list:
                cache_entry = db.query(OddsCache).filter(OddsCache.sport_key == sport_key).first()
                if cache_entry and isinstance(cache_entry.data, list):
                    events_list = cache_entry.data

            upcoming_db_matches = (
                db.query(Match)
                .filter(
                    Match.league_id == league_obj.league_id,
                    Match.status.in_(["SCHEDULED", "LOCKED"]),
                )
                .all()
            )

            placed_dc = 0
            placed_xgb = 0

            for m in upcoming_db_matches:
                match_odds = odds_fetcher.get_odds_for_match(
                    m.home_team, m.away_team, events_list, sport_key
                )

                # Dixon-Coles 1X2 -arvovedot
                latest_pred = (
                    db.query(MatchPrediction)
                    .filter(MatchPrediction.match_id == m.match_id)
                    .order_by(MatchPrediction.created_at.desc())
                    .first()
                )

                if latest_pred:
                    dc_value = calculate_value_bets(
                        latest_pred.prob_home_win,
                        latest_pred.prob_draw,
                        latest_pred.prob_away_win,
                        match_odds.get("H", 0.0),
                        match_odds.get("D", 0.0),
                        match_odds.get("A", 0.0),
                    )
                    for b_data in dc_value:
                        outcome = b_data.get("outcome", "")
                        ev_pct = b_data.get("ev_percentage", 0)
                        stake_pct = b_data.get("kelly_stake_pct", 0)
                        odds = b_data.get("odds", 0)
                        if ev_pct > 0 and stake_pct >= 0.1:
                            if BankrollService.place_value_bet(
                                db=db,
                                match_id=m.match_id,
                                match_name=f"{m.home_team} vs {m.away_team}",
                                outcome=outcome,
                                odds=odds,
                                ev_pct=ev_pct,
                                stake_pct=stake_pct,
                                league_code=code,
                                market_type="1X2",
                                portfolio="poisson",
                            ):
                                placed_dc += 1

                # XGBoost 1X2 -arvovedot
                xgb_analysis = get_xgb_value_analysis(db, m, code, events_list)
                if xgb_analysis:
                    for b_data in xgb_analysis:
                        outcome = b_data.get("outcome", "")
                        ev_pct = b_data.get("ev_percentage", 0)
                        stake_pct = b_data.get("kelly_stake_pct", 0)
                        odds = b_data.get("odds", 0)
                        if ev_pct > 0 and stake_pct >= 0.1:
                            if BankrollService.place_value_bet(
                                db=db,
                                match_id=m.match_id,
                                match_name=f"{m.home_team} vs {m.away_team}",
                                outcome=outcome,
                                odds=odds,
                                ev_pct=ev_pct,
                                stake_pct=stake_pct,
                                league_code=code,
                                market_type="1X2",
                                portfolio="xgboost",
                            ):
                                placed_xgb += 1

            if placed_dc > 0 or placed_xgb > 0:
                print(f"  💰 Uusia arvovetoja asetettu liigassa {code}: Dixon-Coles ({placed_dc} kpl), XGBoost ({placed_xgb} kpl)")

    db.close()
    print("\n=== KAIKKI TOP 5 LIIGAT KÄSITELTY ONNISTUNEESTI ===")

if __name__ == "__main__":
    run_pipeline()