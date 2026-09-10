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
        print("Telegram tokens missing!", flush=True)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=5)
        print(f"Telegram Response: {response.status_code}", flush=True)
    except Exception as e:
        print(f"Telegram Error: {e}", flush=True)

def fetch_kooora_matches():
    global sent_matches
    print("بدء عملية فحص موقع كووورة للمباريات...", flush=True)
    try:
        url = "https://www.kooora.com/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'ar,en-US;q=0.9,en;q=0.8'
        }
        response = requests.get(url, headers=headers, timeout=15)
        print(f"Kooora HTTP Status: {response.status_code}", flush=True)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            elements = soup.find_all(['div', 'tr', 'li'])
            
            found_count = 0
            for el in elements:
                text = el.get_text(separator=" ", strip=True)
                
                # تصفية دقيقة: يجب أن يحتوي العنصر على كلمات انتهاء المباراة
                has_ended = "انتهت" in text or "FT" in text or "Full Time" in text
                
                # تصفية إضافية لضمان أنها مباراة وليست مقالاً (تحتوي على أرقام نتائج أو رمز ضد مثل ضد أو -)
                is_match_format = "-" in text or ":" in text or any(char.isdigit() for char in text)
                
                if has_ended and is_match_format and len(text) < 120:
                    match_name = text.replace('\n', ' - ')[:50]
                    # استبعاد النصوص التي تبدو كعناوين أخبار عامة
                    if "يومًا" in match_name or "الحرب" in match_name or "من الغياب" in match_name:
                        continue
                        
                    found_count += 1
                    if match_name not in sent_matches:
                        message = f"🚨 *تنبيه فجوة تأخير عاجل!*\n\nالمباراة: {match_name}\nالحالة: انتهت في كووورة ولكنها مستمرة في المنصة!\n⚡ سارع بالتحقق واغتنام الفرصة!"
                        send_telegram_message(message)
                        sent_matches.add(match_name)
                        
            print(f"تم رصد {found_count} مباراة حقيقية منتهية.", flush=True)
        else:
            print(f"موقع كووورة رفض الاتصال برمز: {response.status_code}", flush=True)
            
        print("تم الانتهاء من دورة الفحص.", flush=True)
    except Exception as e:
        print(f"Scraping Error Details: {e}", flush=True)

def background_tracker():
    print("خيط الخلفية (Background Tracker) بدأ بالعمل...", flush=True)
    while True:
        try:
            fetch_kooora_matches()
        except Exception as err:
            print(f"Error in background loop: {err}", flush=True)
        time.sleep(60)

@app.route('/')
def home():
    return "Kooora Match Tracker is Running Live!"

if __name__ == '__main__':
    t = threading.Thread(target=background_tracker, daemon=True)
    t.start()
    
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
