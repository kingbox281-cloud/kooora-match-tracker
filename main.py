import os
import time
import threading
import requests
from datetime import datetime
from flask import Flask
from bs4 import BeautifulSoup

# إعداد تطبيق Flask لإبقاء البوت يعمل 24/7 على Render
app = Flask('')

@app.route('/')
def home():
    return "Bot is running and monitoring Kooora 24/7!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# إعدادات تيليجرام (يتم سحبها من متغيرات البيئة في Render أو ضعها هنا مباشرة)
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', 'YOUR_CHAT_ID')

KOOORA_URL = "https://www.kooora.com/?matches=today"

# قائمة المنصات الـ 18 المستهدفة
TARGET_BOOKMAKERS = [
    "Tipico", "Tipwin", "Merkur Bets", "sportwetten.de", "NEO.bet", 
    "bet365", "Winamax", "bwin", "Betano", "Bet-at-home", 
    "ODDSET", "Interwetten", "DAZN Bet", "AdmiralBet", "Betway", 
    "LeoVegas", "VBET", "Bet3000"
]

# ذاكرة مؤقتة لمنع تكرار إرسال التنبيه لنفس المباراة
sent_alerts = set()

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Error sending telegram message: {e}")
        return None

def format_and_send_alert(match_name, league, status_type):
    current_time = datetime.now().strftime("%H:%M:%S")
    
    if status_type == "FT":
        status_text = "انتهت المباراة (FT) ✅"
        title = "🚨 تنبيه فرصة انتهاء مباراة (FT)"
    else:
        status_text = "انتهى الشوط الأول (HT) ⏸️"
        title = "🟡 تنبيه فرصة انتهاء الشوط الأول (HT)"
        
    message = (
        f"{title}\n"
        f"⚽ المباراة: **{match_name}**\n"
        f"🌍 الدولة / البطولة: **{league}**\n"
        f"⏰ وقت التحديث: `{current_time}`\n"
        f"📌 الحالة الرسمية (كووورة): {status_text}\n\n"
        f"⚠️ **المنصات المستهدفة للفحص السريع:**\n"
    )
    
    for bookie in TARGET_BOOKMAKERS:
        message += f"• {bookie} 🟡\n"
        
    message += f"\n⚡ **سارع بالتحقق واغتنام الفرصة!**"
    
    send_telegram_message(message)

def check_kooora_matches():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(KOOORA_URL, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"Failed to fetch Kooora, status code: {response.status_code}")
            return
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # تحليل مباريات الصفحة والبحث عن الحالات المستهدفة (HT / FT)
        matches = soup.find_all('div', class_='match')
        
        for match in matches:
            # استخراج المعرف الفريد للمباراة، اسم الفريقين، البطولة، والحالة
            # يتم تفعيل الشروط هنا ومقارنتها مع مجموعة sent_alerts لمنع التكرار
            pass
            
    except Exception as e:
        print(f"Error scraping Kooora: {e}")

def bot_loop():
    while True:
        check_kooora_matches()
        # فحص الموقع كل 60 ثانية
        time.sleep(60)

if __name__ == "__main__":
    # تشغيل سيرفر الفلاسك في خلفية مستقلة لإبقاء البوت نشطاً على Render
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    # بدء حلقة العمل المستمرة للبوت
    bot_loop()
