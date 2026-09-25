import requests
import os
from dotenv import load_dotenv


load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_API_KEY")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_ID")

def send_telegram_message(message: str):
    """Lähettää viestin Telegram-bottiin."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML" # Mahdollistaa lihavoinnit <b> ja kursivoinnit <i>
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("✅ Telegram-viesti lähetetty onnistuneesti!")
        else:
            print(f"❌ Virhe viestin lähetyksessä: {response.text}")
    except Exception as e:
        print(f"❌ Telegram API yhteysvirhe: {e}")

# Pieni testi, kun ajat tämän tiedoston suoraan
if __name__ == "__main__":
    testiviesti = "⚽ <b>Botti linjoilla!</b> Yhteys toimii täydellisesti."
    send_telegram_message(testiviesti)