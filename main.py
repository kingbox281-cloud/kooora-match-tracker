import os
import time
import threading
import requests
from bs4 import BeautifulSoup
from flask import Flask

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Error: {e}")

def fetch_kooora_matches():
    matches_list = []
    try:
        url = "https://www.kooora.com/?matches=today"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            for match in soup.find_all('div', class_='match')[:5]:
                name = match.text.strip().replace('\n', ' - ')
                if len(name) > 5:
                    matches_list.append({
                        "name": name[:50],
                        "kooora_status": "Live",
                        "platforms": [{"name": "Tipwin", "status": "Active"}]
                    })
    except Exception as e:
        print(f"خطأ: {e}")
    return matches_list

def background_monitor():
    while True:
        try:
            matches = fetch_kooora_matches()
            print(f"تم فحص المباريات: عدد المباريات المكتشفة {len(matches)}")
        except Exception as e:
            print(f"Monitor error: {e}")
        time.sleep(60)

@app.route('/')
def home():
    return "Kooora Match Tracker is Running!"

if __name__ == '__main__':
    threading.Thread(target=background_monitor, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
