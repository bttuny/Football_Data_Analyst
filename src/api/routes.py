# src/api/routes.py
import time
import os
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Depends, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from jose import jwt, JWTError

from src.core.config import LEAGUES_CONFIG
from src.core.database import get_db, Base, engine
from src.models.entities import Match, MatchPrediction, League, User, PaperBet, OddsCache, CardsModelCache
from src.ingestion.odds_fetcher import OddsFetcher
from src.ingestion.historical_data import CardsDataFetcher
from src.quant.value_finder import calculate_value_bets
from src.quant.cards_model import PremierLeagueCardsModel, clean_name
from src.services.bankroll_service import BankrollService
from src.core.security import SECRET_KEY, ALGORITHM, verify_password, create_access_token


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Top 5 Leagues Quant Analytics API")
templates = Jinja2Templates(directory="templates")

# Dynaamiset muistit
league_cards_models = {}



def get_last_odds_update_time(db: Session):
    # Hakee tietokannasta viimeisimmän päivitysajan
    latest = db.query(OddsCache).order_by(OddsCache.updated_at.desc()).first()
    if not latest or not latest.updated_at:
        return "Ei kertoimia"
    dt_helsinki = latest.updated_at.astimezone(ZoneInfo("Europe/Helsinki"))
    return dt_helsinki.strftime("%d.%m. klo %H:%M")


def get_cards_model(code: str, db: Optional[Session] = None) -> PremierLeagueCardsModel:
    """Hakee mallin: 1) RAM-muistista, 2) tietokannasta, 3) CSV lennosta (hidas fallback)."""
    # 1. RAM-välimuisti (saman prosessin sisällä instant)
    model = league_cards_models.get(code)
    if model and len(model.team_card_factors) > 0:
        return model

    # 2. Tietokannasta (nopea, ~50ms — toimii Render cold start -tilanteissa!)
    if db:
        cache = db.query(CardsModelCache).filter(CardsModelCache.league_code == code).first()
        if cache and cache.team_card_factors:
            new_model = PremierLeagueCardsModel()
            new_model.league_avg_cards = float(cache.league_avg_cards)
            new_model.team_card_factors = cache.team_card_factors
            new_model.referee_factors = cache.referee_factors or {}
            league_cards_models[code] = new_model
            print(f"[DB] Korttimalli {code} ladattu tietokannasta!")
            return new_model

    # 3. Fallback: ladataan CSV netista (hidas, vain jos DB tyhja)
    print(f"[CSV] Korttimallia {code} ei loytynyt muistista/DB:sta. Ladataan lennosta...")
    new_model = PremierLeagueCardsModel()
    
    fetcher = CardsDataFetcher()
    league_cfg = LEAGUES_CONFIG.get(code, {})
    csv_code = league_cfg.get("csv_code", "E0")
    
    try:
        df = fetcher.fetch_cards_history(league_csv=csv_code)
        
        if not df.empty:
            new_model.fit(df)
            print(f"[OK] Korttimalli opetettu lennosta liigalle {code} ({len(df)} ottelua).")
        else:
            print(f"[WARN] Korttidataa ei saatu ladattua liigalle {code}.")
    except Exception as e:
        print(f"[WARN] Virhe korttimallin latauksessa/opetuksessa ({code}): {e}")
            
    league_cards_models[code] = new_model
    return new_model


def get_league_referees(db: Optional[Session] = None):
    """Hakee dynaamisesti ladatuista malleista kaikkien liigojen tuomarit."""
    ref_map = {}
    for code in LEAGUES_CONFIG.keys():
        model = get_cards_model(code, db=db)
        ref_list = []
        for name, factor in model.referee_factors.items():
            if len(name) > 2:
                ref_list.append({
                    "name": name.title(),
                    "factor": round(float(factor), 2)
                })
        ref_list.sort(key=lambda x: x["name"])
        ref_map[code] = ref_list
    return ref_map


def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})

    try:
        if token.startswith("Bearer "):
            token = token.split(" ")[1]
            
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username or not isinstance(username, str):
            raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
            
    except JWTError:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
        
    return user


@app.post("/api/v1/odds/refresh")
def refresh_odds(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Vain admin-käyttäjällä on oikeus päivittää kertoimia.")

    odds_fetcher = OddsFetcher()
    
    for code, conf in LEAGUES_CONFIG.items():
        sport_key = conf.get("odds_key")
        if sport_key:
            print(f"🔄 Manuaalinen päivitys: {sport_key}...")
            try:
                fetched_data = odds_fetcher.fetch_current_odds(sport_key=sport_key)
                data_to_save = fetched_data if isinstance(fetched_data, list) else []
                
                # Tallennetaan kertoimet tietokantaan (Insert tai Update)
                cache_entry = db.query(OddsCache).filter(OddsCache.sport_key == sport_key).first()
                if cache_entry:
                    cache_entry.data = data_to_save
                    cache_entry.updated_at = datetime.now(timezone.utc)
                else:
                    new_cache = OddsCache(sport_key=sport_key, data=data_to_save)
                    db.add(new_cache)
                    
                db.commit()
            except Exception as e:
                print(f"⚠️ Virhe haettaessa kertoimia {sport_key}: {e}")
                
    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=303)


@app.get("/api/v1/predictions/upcoming")
def get_upcoming_predictions(
    league: Optional[str] = None, db: Session = Depends(get_db)
):
    query = (
        db.query(Match)
        .filter(Match.status.in_(["SCHEDULED", "LOCKED"]))
        .order_by(Match.match_datetime.asc())
    )

    if league and league != "ALL":
        query = query.join(League).filter(League.code == league)

    matches = query.limit(50).all()
    odds_fetcher = OddsFetcher()
    results = []

    for m in matches:
        l_code = m.league.code if m.league else "PL"
        sport_key = LEAGUES_CONFIG.get(l_code, {}).get("odds_key", "soccer_epl")

        cache_entry = db.query(OddsCache).filter(OddsCache.sport_key == sport_key).first()
        events_list = cache_entry.data if cache_entry and isinstance(cache_entry.data, list) else []
        
        match_odds = odds_fetcher.get_odds_for_match(
            m.home_team, m.away_team, events_list, sport_key
        )

        latest_pred = (
            db.query(MatchPrediction)
            .filter(MatchPrediction.match_id == m.match_id)
            .order_by(MatchPrediction.created_at.desc())
            .first()
        )

        if latest_pred:
            prob_h = latest_pred.prob_home_win
            prob_d = latest_pred.prob_draw
            prob_a = latest_pred.prob_away_win

            value_analysis = calculate_value_bets(
                prob_h, prob_d, prob_a,
                match_odds.get("H", 0.0), match_odds.get("D", 0.0), match_odds.get("A", 0.0),
            )

            for b_data in value_analysis:
                outcome = b_data.get("outcome", "")
                ev_pct = b_data.get("ev_percentage", 0)
                stake_pct = b_data.get("kelly_stake_pct", 0)
                odds = b_data.get("odds", 0)

                if ev_pct > 0 and stake_pct >= 0.1:
                    BankrollService.place_value_bet(
                        db=db,
                        match_id=m.match_id,
                        match_name=f"{m.home_team} vs {m.away_team}",
                        outcome=outcome,
                        odds=odds,
                        ev_pct=ev_pct,
                        stake_pct=stake_pct,
                        league_code=l_code,
                        market_type="1X2"
                    )

            c_model = get_cards_model(l_code, db=db)
            card_pred = c_model.predict_cards(m.home_team, m.away_team, referee=m.referee)
            
            h_clean = clean_name(m.home_team)
            a_clean = clean_name(m.away_team)
            h_f = next((v for k, v in c_model.team_card_factors.items() if len(k) > 2 and k in h_clean), 1.0)
            a_f = next((v for k, v in c_model.team_card_factors.items() if len(k) > 2 and k in a_clean), 1.0)
            card_pred["base_lambda"] = round(c_model.league_avg_cards * ((h_f + a_f) / 2.0), 2)

            formatted_time = ""
            if m.match_datetime:
                dt_utc = m.match_datetime
                if dt_utc.tzinfo is None:
                    dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                dt_helsinki = dt_utc.astimezone(ZoneInfo("Europe/Helsinki"))
                formatted_time = dt_helsinki.strftime("%d.%m. klo %H:%M")

            results.append({
                "match_id": m.match_id,
                "league_code": l_code,
                "league_name": m.league.name if m.league else "Valioliiga",
                "match_datetime": formatted_time,
                "home_team": m.home_team,
                "away_team": m.away_team,
                "expected_goals": {
                    "home": float(latest_pred.predicted_home_xg),
                    "away": float(latest_pred.predicted_away_xg),
                },
                "value_analysis": value_analysis,
                "cards_analysis": card_pred,
            })
    return results


@app.get("/", response_class=HTMLResponse)
def render_dashboard(
    request: Request, 
    league: str = "ALL", 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    predictions = get_upcoming_predictions(league=league, db=db)
    referees_by_league = get_league_referees(db=db)
    last_updated = get_last_odds_update_time(db)

    return templates.TemplateResponse(
        request,
        "views/dashboard.html",
        {
            "predictions": predictions,
            "active_tab": "matches",
            "current_league": league,
            "leagues_config": LEAGUES_CONFIG,
            "referees_by_league": referees_by_league,
            "last_updated": last_updated,
            "current_user": current_user,
        },
    )


@app.get("/bankroll", response_class=HTMLResponse)
def render_bankroll(
    request: Request, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    summary = BankrollService.get_portfolio_summary(db)
    return templates.TemplateResponse(
        request,
        "views/bankroll.html",
        {"summary": summary, "active_tab": "bankroll", "current_user": current_user},
    )


@app.post("/api/v1/bets/cards")
def place_card_bet(
    request: Request,
    match_id: int = Form(...),
    match_name: str = Form(...),
    league_code: str = Form("PL"),
    selected_line: float = Form(3.5),
    user_odds: float = Form(...),
    line_prob: float = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Vain admin-käyttäjällä on oikeus asettaa korttivetoja.")

    if user_odds > 1.0 and line_prob > 0:
        ev = (line_prob * user_odds) - 1.0
        b = user_odds - 1.0
        kelly = ((b * line_prob) - (1.0 - line_prob)) / b if b > 0 else 0
        stake_pct = min(2.0, round(max(0.0, kelly * 0.25) * 100, 1))

        if ev > 0.02 and stake_pct >= 0.1:
            market_type = f"CARDS_OVER_{str(selected_line).replace('.', '_')}"
            BankrollService.place_value_bet(
                db=db,
                match_id=match_id,
                match_name=match_name,
                outcome=f"Yli {selected_line}",
                odds=user_odds,
                ev_pct=round(ev * 100, 1),
                stake_pct=stake_pct,
                league_code=league_code,
                market_type=market_type
            )
    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=303)

@app.post("/api/v1/bets/{bet_id}/resolve")
def resolve_bet(
    bet_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Vain admin-käyttäjällä on oikeus ratkaista vetoja.")

    # TÄSSÄ ON SE KRIITTINEN MUUTOS: PaperBet.bet_id
    bet = db.query(PaperBet).filter(PaperBet.bet_id == bet_id).first()
    
    if not bet:
        raise HTTPException(status_code=404, detail="Vetoa ei löytynyt.")

    if status == "WON":
        bet.status = "WON"
        bet.pnl = float(bet.stake_amount) * (float(bet.odds) - 1.0)
    elif status == "LOST":
        bet.status = "LOST"
        bet.pnl = -float(bet.stake_amount)

    db.commit()
    
    return RedirectResponse(url="/bankroll", status_code=303)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "views/login.html", {})


@app.post("/login")
def login_post(
    username: str = Form(...), 
    password: str = Form(...), 
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    
    if not user or not verify_password(password, user.hashed_password):
        return RedirectResponse(url="/login?error=1", status_code=303)

    access_token_expires = timedelta(minutes=60 * 24 * 7)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role}, 
        expires_delta=access_token_expires
    )

    is_production = os.getenv("RENDER", "false").lower() == "true"
    redirect_response = RedirectResponse(url="/", status_code=303)
    redirect_response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=60 * 24 * 7 * 60,
        samesite="lax",
        secure=is_production
    )
    return redirect_response


@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("access_token")
    return response