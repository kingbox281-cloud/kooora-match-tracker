import os
import time
import threading
import requests
from bs4 import BeautifulSoup
from flask import Flask

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# مجموعة لحفظ المباريات التي تم إرسال تنبيه لها لعدم تكرارها
sent_matches = set()

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
    global sent_matches
    try:
        url = "https://www.kooora.com/?matches=today"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # البحث عن المباريات
            for match in soup.find_all('div', class_='match'):
                text = match.text.strip()
                if "انتهت" in text or "FT" in text or "Full Time" in text:
                    match_name = text.replace('\n', ' - ')[:50]
                    
                    # التحقق مما إذا تم إرسال تنبيه لهذه المباراة من قبل
                    if match_name not in sent_matches:
                        message = f"🚨 *تنبيه فجوة تأخير عاجل!*\n\nالمباراة: {match_name}\nالحالة: انتهت في كووورة ولكنها مستمرة في المنصة!\n⚡ سارع بالتحقق واغتنام الفرصة!"
                        send_telegram_message(message)
                        sent_matches.add(match_name)
        print("تم فحص المباريات بنجاح...")
    except Exception as e:
        print(f"Scraping Error: {e}")

def background_tracker():
    """حلقة تكرار تعمل في الخلفية لفحص المباريات كل 60 ثانية"""
    while True:
        fetch_kooora_matches()
        time.sleep(60) # الانتظار لمدة دقيقة قبل الفحص التالي

@app.route('/')
def home():
    return "Kooora Match Tracker is Running Live!"

if __name__ == '__main__':
    # تشغيل حلقة التكرار في خيط منفصل (Background Thread)
    t = threading.Thread(target=background_tracker, daemon=True)
    t.start()
    
    # تشغيل سيرفر Flask لاستيفاء متطلبات Render
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
