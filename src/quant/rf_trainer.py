import pandas as pd
import os
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report

LEAGUE_ID_MAPPING = {
    2: "EPL",
    3: "La Liga",
    4: "Bundesliga",
    5: "Serie A",
    6: "Ligue 1"
}

def train_league_models():
    file_path = "data/ml_training_data.csv"
    if not os.path.exists(file_path):
        print(f"Virhe: Dataa ei löydy polusta {file_path}")
        return

    df = pd.read_csv(file_path)
    
    features = [
        'home_xg_avg_5', 'home_xga_avg_5', 'home_gf_avg_5', 'home_ga_avg_5',
        'away_xg_avg_5', 'away_xga_avg_5', 'away_gf_avg_5', 'away_ga_avg_5'
    ]
    
    os.makedirs("models", exist_ok=True)
    
    # Haetaan datasta kaikki uniikit liigat (league_id)
    unique_leagues = df['league_id'].unique()
    
    print(f"Löydettiin {len(unique_leagues)} eri liigaa. Aloitetaan mallien koulutus!\n")

    for league_id in unique_leagues:
        league_name = LEAGUE_ID_MAPPING.get(league_id, f"League_{league_id}")
        
        print(f"{'='*50}")
        print(f"KOULUTETAAN MALLI: {league_name.upper()}")
        print(f"{'='*50}")
        
        # Suodatetaan DataFrame vain tämän liigan otteluihin
        league_df = df[df['league_id'] == league_id].copy()
        
        X = league_df[features]
        y = league_df['target'] 
        
        # Jaetaan tämän liigan data (80% opetus, 20% testi) aikajärjestyksessä
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
        
        # Koulutetaan Random Forest juuri tälle liigalle
        rf_model = RandomForestClassifier(
            n_estimators=100, 
            max_depth=5, 
            random_state=42, 
            class_weight='balanced'
        )
        rf_model.fit(X_train, y_train)
        
        # Arvioidaan tulokset
        y_pred = rf_model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        
        print(f"Opetusdata: {len(X_train)} ottelua | Testidata: {len(X_test)} ottelua")
        print(f"Osumatarkkuus (Accuracy): {accuracy * 100:.1f} %")
        print(classification_report(y_test, y_pred, zero_division=0))
        
        # Tallennetaan liigakohtainen malli
        safe_name = league_name.lower().replace(" ", "_")
        model_path = f"models/rf_{safe_name}_v1.pkl"
        joblib.dump(rf_model, model_path)
        print(f"Tallennettu: {model_path}\n")

if __name__ == "__main__":
    train_league_models()