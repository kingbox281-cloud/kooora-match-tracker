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
    finished_matches = []
    try:
        url = "https://www.kooora.com/?matches=today"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # البحث عن المباريات التي تظهر حالياً في كووورة وانتهت أو أغلقت
            for match in soup.find_all('div', class_='match'):
                text = match.text.strip()
                # التحقق مما إذا كانت المباراة منتهية أو انتهى وقتها
                if "انتهت" in text or "FT" in text or "Full Time" in text:
                    match_name = text.replace('\n', ' - ')[:50]
                    finished_matches.append(match_name)
                    
                    # إرسال تنبيه فوري عبر تيليجرام يوضح أن المباراة انتهت في كووورة
                    alert_text = (
                        f"🚨 *تنبيه فرصة Delay Betting*\n\n"
                        f"⚽ *المباراة:* {match_name}\n"
                        f"📌 *الحالة:* انتهت في كووورة!\n"
                        f"⚠️ *تحقق فوراً من:* Tipwin / Merkur Bets / sportwetten.de (قد تكون لم تُغلق بعد)"
                    )
                    send_telegram_message(alert_text)
                    
    except Exception as e:
        print(f"خطأ أثناء جلب المباريات: {e}")
    return finished_matches

def background_monitor():
    while True:
        try:
            print("جاري فحص حالة المباريات للتأكد من المباريات المنتهية...")
            fetch_kooora_matches()
        except Exception as e:
            print(f"Monitor error: {e}")
        time.sleep(60)  # يتم الفحص تلقائياً كل دقيقة

@app.route('/')
def home():
    return "Kooora Delay Betting Monitor is Running!"

if __name__ == '__main__':
    threading.Thread(target=background_monitor, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
