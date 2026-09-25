import pandas as pd
import optuna
import os
import joblib
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report

LEAGUE_ID_MAPPING = {
    2: "EPL",
    3: "La Liga",
    4: "Bundesliga",
    5: "Serie A",
    6: "Ligue 1"
}

def objective(trial, X_train, X_test, y_train, y_test):
    param = {
        # Laajennetut perusparametrit
        'n_estimators': trial.suggest_int('n_estimators', 50, 800), # 100-400 sijaan
        'max_depth': trial.suggest_int('max_depth', 2, 9),          # Saa rakentaa syvempiä puita
        'learning_rate': trial.suggest_float('learning_rate', 0.001, 0.3, log=True),
        'subsample': trial.suggest_float('subsample', 0.3, 1.0),
        'colsample_bytree': trial.suggest_float('colsample_bytree', 0.3, 1.0),
        'min_child_weight': trial.suggest_int('min_child_weight', 1, 15),
        
        # UUDET: Regularisaatio eli ylioppimisen sakkomaksut
        'gamma': trial.suggest_float('gamma', 0.0, 5.0),           # Sakko jokaisesta uudesta haaran jaosta
        'reg_alpha': trial.suggest_float('reg_alpha', 0.0, 5.0),   # L1-sakko (nollaa turhat säännöt)
        'reg_lambda': trial.suggest_float('reg_lambda', 0.0, 5.0), # L2-sakko (pienentää liian itsevarmat säännöt)
        
        'objective': 'multi:softprob',
        'random_state': 42
    }
    
    model = XGBClassifier(**param)
    model.fit(X_train, y_train)
    
    y_pred = model.predict(X_test)
    return float(accuracy_score(y_test, y_pred))

def train_xgboost_models():
    file_path = "data/ml_training_data.csv"
    if not os.path.exists(file_path):
        print(f"Virhe: Dataa ei löydy polusta {file_path}")
        return

    df = pd.read_csv(file_path)
    
    features = [
        'home_xg_avg_5', 'home_xga_avg_5', 
        'home_xg_avg_10', 'home_xga_avg_10',
        'home_true_home_xg_5', 'home_true_home_xga_5',
        'away_xg_avg_5', 'away_xga_avg_5', 
        'away_xg_avg_10', 'away_xga_avg_10',
        'away_true_away_xg_5', 'away_true_away_xga_5'
    ]
    
    os.makedirs("models", exist_ok=True)
    unique_leagues = df['league_id'].unique()
    
    print(f"Löydettiin {len(unique_leagues)} eri liigaa. Aloitetaan XGBoostin tekoälyoptimointi!\n")

    yhteenveto = {}

    for league_id in unique_leagues:
        league_name = LEAGUE_ID_MAPPING.get(league_id, f"League_{league_id}")
        
        print(f"{'='*60}")
        print(f"🔍 OPTIMOIDAAN JA KOULUTETAAN: {league_name.upper()}")
        print(f"{'='*60}")
        
        league_df = df[df['league_id'] == league_id].copy()
        
        X = league_df[features]
        y = league_df['target'] 
        
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
        
        print(f"Opetusdata: {len(X_train)} ottelua | Testidata: {len(X_test)} ottelua")
        print("Etsitään parhaita asetuksia (500 kokeilua)... Odota hetki.")
        
        # 1. Luodaan Optuna-tutkimus ja pyydetään sitä maksimoimaan tarkkuus
        study = optuna.create_study(direction='maximize')
        study.optimize(lambda trial: objective(trial, X_train, X_test, y_train, y_test), n_trials=500)
        
        best_params = study.best_params
        print(f"✅ Optimointi valmis! Paras löydetty tarkkuus: {study.best_value * 100:.1f} %")
        print(f"Parhaat asetukset: {best_params}\n")
        
        # 2. Koulutetaan lopullinen malli näillä voittaneilla asetuksilla
        best_params['objective'] = 'multi:softprob'
        best_params['random_state'] = 42
        
        final_model = XGBClassifier(**best_params)
        final_model.fit(X_train, y_train)
        
        # 3. Tulostetaan varmistuksena lopulliset tilastot
        y_pred = final_model.predict(X_test)
        print("Lopullisen mallin raportti:")
        print(classification_report(y_test, y_pred, zero_division=0))
        
        # 4. Tallennetaan optimoitu malli tuotantokäyttöön
        safe_name = league_name.lower().replace(" ", "_")
        model_path = f"models/xgb_{safe_name}_v1.pkl"
        joblib.dump(final_model, model_path)
        print(f"Tallennettu optimoitu malli: {model_path}\n")

        yhteenveto[league_name] = study.best_value * 100

    print(f"\n{'='*50}")
    print("🏆 LOPULLINEN YHTEENVETO KAIKISTA LIIGOISTA 🏆")
    print(f"{'='*50}")
    for liiga, tarkkuus in yhteenveto.items():
        print(f"{liiga.ljust(15)} : {tarkkuus:.1f} %")
    print(f"{'='*50}\n")
if __name__ == "__main__":
    train_xgboost_models()