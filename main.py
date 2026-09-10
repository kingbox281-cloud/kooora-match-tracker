import os
import time
import threading
import requests
from bs4 import BeautifulSoup
from flask import Flask

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

sent_matches = set()

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram tokens missing!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=5)
        print(f"Telegram Response: {response.status_code}")
    except Exception as e:
        print(f"Telegram Error: {e}")

def fetch_kooora_matches():
    global sent_matches
    print("بدء عملية فحص موقع كووورة للمباريات...")
    try:
        url = "https://www.kooora.com/?matches=today"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Kooora HTTP Status: {response.status_code}")
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            matches = soup.find_all('div', class_='match')
            print(f"تم العثور على {len(-matches if 'matches' in locals() else [])} عنصر مباراة في الصفحة.") # للتتبع
            
            for match in matches:
                text = match.text.strip()
                if "انتهت" in text or "FT" in text or "Full Time" in text:
                    match_name = text.replace('\n', ' - ')[:50]
                    if match_name not in sent_matches:
                        message = f"🚨 *تنبيه فجوة تأخير عاجل!*\n\nالمباراة: {match_name}\nالحالة: انتهت في كووورة ولكنها مستمرة في المنصة!\n⚡ سارع بالتحقق واغتنام الفرصة!"
                        send_telegram_message(message)
                        sent_matches.add(match_name)
        print("تم الانتهاء من دورة الفحص بنجاح.")
    except Exception as e:
        print(f"Scraping Error Details: {e}")

def background_tracker():
    print("خيط الخلفية (Background Tracker) بدأ بالعمل...")
    while True:
        try:
            fetch_kooora_matches()
        except Exception as err:
            print(f"Error in background loop: {err}")
        time.sleep(60)

@app.route('/')
def home():
    return "Kooora Match Tracker is Running Live!"

if __name__ == '__main__':
    # بدء الخيط الخلفي قبل تشغيل سيرفر فلاسك
    t = threading.Thread(target=background_tracker, daemon=True)
    t.start()
    
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
