import difflib
import os
import pandas as pd
import joblib
from datetime import datetime, timezone, time
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

# Omat tuonnit
from src.core.config import LEAGUES_CONFIG
from src.core.database import SessionLocal
from src.models.entities import Match, League, OddsCache
from src.ingestion.odds_fetcher import OddsFetcher, clean_team_name
from src.notifications.telegram_sender import send_telegram_message

_MODELS_CACHE: Dict[str, Any] = {}


def get_db_history_name(db: Session, team_name: str, league_id: int) -> Optional[str]:
    """
    Etsii joukkueen nimen, jolla sen historialliset xG-datat on tallennettu
    tietokantaan. Käyttää monivaiheista fuzzy-matchingia:
      1. Tarkka clean_team_name()-vertailu xG-joukkueisiin
      2. Substring-tarkistus (esim. "brighton" in "brighton and hove albion")
      3. SequenceMatcher (ratio >= 0.78)
      4. Jos ei löydy xG-joukkueista, etsii liigan kaikista joukkueista (jotta
         joukkue tunnistetaan tietokannasta ja ohitus tapahtuu puuttuvan xG-datan
         vuoksi eikä väärän 'ei löydy tietokannasta' -virheen vuoksi).
    """
    target_clean = clean_team_name(team_name)
    
    if not target_clean:
        return None

    # Haetaan uniikit joukkueiden nimet tästä liigasta joissa on xG-data
    home_teams = db.query(Match.home_team).filter(
        Match.league_id == league_id, 
        Match.status == "FINISHED",
        Match.home_xg.is_not(None)
    ).distinct().all()
    
    away_teams = db.query(Match.away_team).filter(
        Match.league_id == league_id, 
        Match.status == "FINISHED",
        Match.away_xg.is_not(None)
    ).distinct().all()
    
    xg_team_names = set(n for (n,) in home_teams) | set(n for (n,) in away_teams)

    # Rakennetaan sanakirja: puhdistettu nimi -> alkuperäinen DB-nimi (xG-joukkueille)
    cleaned_map: Dict[str, str] = {}
    for raw_name in xg_team_names:
        cleaned_map[clean_team_name(raw_name)] = raw_name
    
    # Vaihe 1: Tarkka osuma puhdistetulla nimellä
    if target_clean in cleaned_map:
        return cleaned_map[target_clean]
    
    # Vaihe 2: Substring-tarkistus
    for db_clean, db_raw in cleaned_map.items():
        if (target_clean in db_clean or db_clean in target_clean) and len(target_clean) >= 4 and len(db_clean) >= 4:
            return db_raw
    
    # Vaihe 3: Fuzzy-matching SequenceMatcherilla (kynnys 0.78)
    best_score = 0.0
    best_raw = None
    for db_clean, db_raw in cleaned_map.items():
        ratio = difflib.SequenceMatcher(None, target_clean, db_clean).ratio()
        if ratio > best_score:
            best_score = ratio
            best_raw = db_raw
    
    if best_score >= 0.78 and best_raw:
        return best_raw

    # Vaihe 4: Etsitään kaikista liigan otteluista (myös ilman xG-dataa olevat joukkueet)
    all_home = db.query(Match.home_team).filter(Match.league_id == league_id).distinct().all()
    all_away = db.query(Match.away_team).filter(Match.league_id == league_id).distinct().all()
    all_league_teams = set(n for (n,) in all_home) | set(n for (n,) in all_away)
    
    all_cleaned = {clean_team_name(r): r for r in all_league_teams}
    if target_clean in all_cleaned:
        return all_cleaned[target_clean]
    for c, r in all_cleaned.items():
        if (target_clean in c or c in target_clean) and len(target_clean) >= 4 and len(c) >= 4:
            return r
    for c, r in all_cleaned.items():
        if difflib.SequenceMatcher(None, target_clean, c).ratio() >= 0.78:
            return r
            
    # Jos mikään ei matchaa, palauta None
    return None


def get_current_team_stats(db: Session, team_name: str, is_home: bool) -> Optional[Dict[str, float]]:
    """
    Hakee tietokannasta joukkueen TÄMÄN HETKEN tilastot (viimeiset 10 peliä ja koti/vieras).
    Palauttaa None jos ei riittävästi dataa (10 yleistä + 5 koti/vieras).
    """
    all_matches = db.query(Match).filter(
        (Match.home_team == team_name) | (Match.away_team == team_name),
        Match.status == "FINISHED",
        Match.home_xg.is_not(None),
        Match.away_xg.is_not(None)
    ).order_by(Match.match_datetime.desc()).limit(10).all()
    
    all_matches = list(reversed(all_matches))
    
    stats_10 = []
    for m in all_matches:
        if m.home_team == team_name:
            stats_10.append({'xg_for': (m.home_xg), 'xg_against': (m.away_xg)})
        else:
            stats_10.append({'xg_for': (m.away_xg), 'xg_against': (m.home_xg)})
            
    if is_home:
        location_matches = db.query(Match).filter(
            Match.home_team == team_name, Match.status == "FINISHED",
            Match.home_xg.is_not(None),
            Match.away_xg.is_not(None)
        ).order_by(Match.match_datetime.desc()).limit(5).all()
    else:
        location_matches = db.query(Match).filter(
            Match.away_team == team_name, Match.status == "FINISHED",
            Match.home_xg.is_not(None),
            Match.away_xg.is_not(None)
        ).order_by(Match.match_datetime.desc()).limit(5).all()
        
    location_matches = list(reversed(location_matches))
    
    stats_loc_5 = []
    for m in location_matches:
        if is_home:
            stats_loc_5.append({'xg_for': (m.home_xg), 'xg_against': (m.away_xg)})
        else:
            stats_loc_5.append({'xg_for': (m.away_xg), 'xg_against': (m.home_xg)})

    if len(stats_10) < 10 or len(stats_loc_5) < 5:
        return None

    stats_5 = stats_10[-5:]

    return {
        'xg_avg_5': sum(x['xg_for'] for x in stats_5) / 5,
        'xga_avg_5': sum(x['xg_against'] for x in stats_5) / 5,
        'xg_avg_10': sum(x['xg_for'] for x in stats_10) / 10,
        'xga_avg_10': sum(x['xg_against'] for x in stats_10) / 10,
        'true_loc_xg_5': sum(x['xg_for'] for x in stats_loc_5) / 5,
        'true_loc_xga_5': sum(x['xg_against'] for x in stats_loc_5) / 5,
    }


def get_xgb_value_analysis(
    db: Session,
    match: Match,
    league_code: str,
    events_list: list,
) -> Optional[List[Dict[str, Any]]]:
    """
    Analysoi yksittäisen ottelun XGBoost-mallilla ja palauttaa arvovetoanalyysin.
    
    Palauttaa None jos:
      - Mallia ei löydy
      - Joukkuetta ei löydy tietokannasta
      - Ei riittävästi xG-dataa (< 10 peliä tai < 5 koti/vieras)
      - Kertoimia ei löydy
    """
    league_cfg = LEAGUES_CONFIG.get(league_code, {})
    league_name = league_cfg.get("name", league_code)
    
    # Haetaan league_id tietokannasta
    league_obj = db.query(League).filter(League.code == league_code).first()
    if not league_obj:
        return None
    league_id = league_obj.league_id

    # 1. Ladataan oikea XGBoost-malli
    safe_league_name = league_name.lower().replace(" ", "_")
    model_path = f"models/xgb_{safe_league_name}_v1.pkl"
    if not os.path.exists(model_path):
        alt_paths = [
            f"models/xgb_{league_code.lower()}_v1.pkl",
            "models/xgb_epl_v1.pkl" if league_code == "PL" else None,
        ]
        for alt in alt_paths:
            if alt and os.path.exists(alt):
                model_path = alt
                break
    
    if not os.path.exists(model_path):
        return None
        
    if model_path not in _MODELS_CACHE:
        _MODELS_CACHE[model_path] = joblib.load(model_path)
    model = _MODELS_CACHE[model_path]

    home_fixture_name = match.home_team
    away_fixture_name = match.away_team
    
    # 2. Nimisilta: yhdistetään fixture-nimi historian DB-nimeen
    home_history_name = get_db_history_name(db, home_fixture_name, league_id)
    away_history_name = get_db_history_name(db, away_fixture_name, league_id)
    
    if not home_history_name:
        print(f"  -> [XGB] Kotijoukkuetta '{home_fixture_name}' ei loydy tietokannasta liigassa {league_code}.")
        return None
    if not away_history_name:
        print(f"  -> [XGB] Vierasjoukkuetta '{away_fixture_name}' ei loydy tietokannasta liigassa {league_code}.")
        return None
    
    # 3. Haetaan xG-tilastot
    home_stats = get_current_team_stats(db, home_history_name, is_home=True)
    away_stats = get_current_team_stats(db, away_history_name, is_home=False)
    
    if not home_stats or not away_stats:
        skip_team = home_fixture_name if not home_stats else away_fixture_name
        print(f"  -> [XGB] Ohitetaan {home_fixture_name} vs {away_fixture_name}: "
              f"Ei riittavasti xG-historiaa ({skip_team}).")
        return None
    
    # 4. Haetaan kertoimet
    odds_fetcher = OddsFetcher()
    prices = odds_fetcher.get_odds_for_match(home_fixture_name, away_fixture_name, events_list)
    
    if prices["H"] == 0.0 or prices["A"] == 0.0:
        return None
        
    # 5. Rakennetaan syöte mallille
    features = pd.DataFrame([{
        'home_xg_avg_5': home_stats['xg_avg_5'],
        'home_xga_avg_5': home_stats['xga_avg_5'],
        'home_xg_avg_10': home_stats['xg_avg_10'],
        'home_xga_avg_10': home_stats['xga_avg_10'],
        'home_true_home_xg_5': home_stats['true_loc_xg_5'],
        'home_true_home_xga_5': home_stats['true_loc_xga_5'],
        
        'away_xg_avg_5': away_stats['xg_avg_5'],
        'away_xga_avg_5': away_stats['xga_avg_5'],
        'away_xg_avg_10': away_stats['xg_avg_10'],
        'away_xga_avg_10': away_stats['xga_avg_10'],
        'away_true_away_xg_5': away_stats['true_loc_xg_5'],
        'away_true_away_xga_5': away_stats['true_loc_xga_5'],
    }])
    
    # 6. Ennustetaan todennäköisyydet: 0=Vieras, 1=Tasan, 2=Koti
    probs = model.predict_proba(features)[0]
    prob_away, prob_draw, prob_home = float(probs[0]), float(probs[1]), float(probs[2])
    
    # 7. Lasketaan arvovedot samassa muodossa kuin calculate_value_bets()
    outcomes = [
        ("H", prob_home, prices["H"], "Kotivoitto"),
        ("D", prob_draw, prices["D"], "Tasapeli"),
        ("A", prob_away, prices["A"], "Vierasvoitto"),
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

        # Sama varianssisäätö kuin value_finder.py:ssä
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


def run_xgboost_value_finder():
    """
    CLI-skripti: ajaa XGBoost-analyysin ja tulostaa tulokset konsoliin.
    Käyttää get_xgb_value_analysis() -funktiota sisäisesti.
    """
    db = SessionLocal()
    odds_fetcher = OddsFetcher()

    print(f"\n{'='*60}")
    print("🚀 KÄYNNISTETÄÄN XGBOOST YLIKERROIN-MOOTTORI")
    print(f"{'='*60}")

    # Alustetaan Telegram-viesti
    telegram_viesti = "⚽ <b>PÄIVÄN YLIKERTOIMET (XGBoost)</b>\n\n"
    loytyi_kohteita = False

    # Määritetään KULUVAN PÄIVÄN alku ja loppu (UTC-ajassa, jota tietokanta käyttää)
    tanaan = datetime.now(timezone.utc).date()
    paivan_alku = datetime.combine(tanaan, time.min).replace(tzinfo=timezone.utc)
    paivan_loppu = datetime.combine(tanaan, time.max).replace(tzinfo=timezone.utc)

    for code, conf in LEAGUES_CONFIG.items():
        league_name = conf["name"]
        odds_key = conf.get("odds_key", "")
        
        print(f"\n🔍 Analysoidaan liigaa: {league_name}...")

        league_obj = db.query(League).filter(League.code == code).first()
        if not league_obj:
            print(f"  -> Liigaa {code} ei löydy tietokannasta.")
            continue

        # Haetaan VAIN TÄMÄN PÄIVÄN tulevat ottelut
        upcoming_matches = db.query(Match).filter(
            Match.league_id == league_obj.league_id,
            Match.status != "FINISHED",
            Match.match_datetime >= paivan_alku,
            Match.match_datetime <= paivan_loppu
        ).all()

        if not upcoming_matches:
            print(f"  -> Ei tämän päivän otteluita tietokannassa.")
            continue

        # Haetaan kertoimet DB-cachesta (tai API fallback)
        cache_entry = db.query(OddsCache).filter(OddsCache.sport_key == odds_key).first()
        events_list = cache_entry.data if cache_entry and isinstance(cache_entry.data, list) else []
        
        if not events_list:
            events_list = odds_fetcher.fetch_current_odds(sport_key=odds_key)
        
        if not events_list:
            print(f"  -> Ei kertoimia saatavilla.")
            continue

        for match in upcoming_matches:
            analysis = get_xgb_value_analysis(db, match, code, events_list)
            
            if not analysis:
                continue
            
            has_value = any(v["is_value"] for v in analysis)
            home = match.home_team
            away = match.away_team
            
            if has_value:
                print(f"\n🔥 YLIKERROIN: {home} vs {away}")
                telegram_viesti += f"🔥 <b>{home} vs {away}</b>\n"
                
                for v in analysis:
                    print(f"   {v['outcome']}: {v['prob']*100:.1f}% | Kerroin: {v['odds']:.2f} | EV: {v['ev_percentage']:+.1f}%")
                    if v["is_value"]:
                        print(f"   👉 PELIVALINTA: {v['outcome']} ({v['label']}) | Panos: {v['kelly_stake_pct']}%")
                        
                        # Lisätään varsinainen pelikohde viestiin
                        telegram_viesti += f"👉 Valinta: <b>{v['outcome']}</b> ({v['label']}) | Kerroin: <b>{v['odds']:.2f}</b>\n"
                        telegram_viesti += f"📊 EV: +{v['ev_percentage']}% | Suosituspanos: {v['kelly_stake_pct']}%\n"
                        loytyi_kohteita = True
                telegram_viesti += "\n" # Tyhjä rivi otteluiden väliin
            else:
                print(f"  -> ❌ {home} vs {away}: Ei ylikerrointa.")

    db.close()
    print(f"\n{'='*60}")
    print("✅ Analyysi valmis!")
    print(f"{'='*60}\n")

    # LÄHETETÄÄN TELEGRAM-VIESTI
    if loytyi_kohteita:
        send_telegram_message(telegram_viesti)
        print("📱 Kohteet lähetetty Telegramiin!")
    else:
        ei_kohteita_msg = "🤖 XGBoost-analyysi valmis.\nTälle päivälle ei löytynyt pelattavia ylikertoimia."
        send_telegram_message(ei_kohteita_msg)
        print("📱 Ilmoitus (ei kohteita) lähetetty Telegramiin!")


if __name__ == "__main__":
    run_xgboost_value_finder()