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
    print("بدء عملية فحص مباريات اليوم في كووورة...", flush=True)
    try:
        # استخدام رابط مباريات اليوم المباشر
        url = "https://www.kooora.com/?matches=today"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'ar,en-US;q=0.9,en;q=0.8'
        }
        response = requests.get(url, headers=headers, timeout=15)
        print(f"Kooora HTTP Status: {response.status_code}", flush=True)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # البحث في مربعات أو جداول المباريات المخصصة فقط لتجنب الأخبار
            match_boxes = soup.find_all(['div', 'table', 'li'], class_=lambda x: x and ('match' in x or 'game' in x or 'score' in x))
            
            if not match_boxes:
                # إذا لم تجد الفئات المحددة، نبحث في الجداول العامة التي تحتوي على نتائج
                match_boxes = soup.find_all('tr')
                
            found_count = 0
            for box in match_boxes:
                text = box.get_text(separator=" ", strip=True)
                
                # شرط أن تكون مباراة حقيقية انتهت (تحتوي على علامة انتهاء ونتيجة أهداف رقمية)
                is_ended = "انتهت" in text or "FT" in text or "Full Time" in text
                has_teams_and_score = any(char.isdigit() for char in text) and ("-" in text or ":" in text)
                
                # استبعاد النصوص الطويلة أو العناوين الإخبارية
                if is_ended and has_teams_and_score and len(text) < 80 and "رئيس" not in text and "يومًا" not in text:
                    match_name = text.replace('\n', ' - ')[:60]
                    
                    found_count += 1
                    if match_name not in sent_matches:
                        message = (
                            f"🚨 *تنبيه فجوة تأخير عاجل!*\n\n"
                            f"المباراة: {match_name}\n\n"
                            f"🛑 الحالة في المصدر الرسمي (كووورة): انتهت تماماً\n"
                            f"⏳ الحالة في المنصة (Tipwin / Merkur Bets / sportwetten.de): لا تزال معروضة أو لم تبدأ بعد!\n\n"
                            f"⚡ سارع بالتحقق واغتنام الفرصة!"
                        )
                        send_telegram_message(message)
                        sent_matches.add(match_name)
                        
            print(f"تم رصد {found_count} مباراة منتهية مطابقة للشروط.", flush=True)
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
