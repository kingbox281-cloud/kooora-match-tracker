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

# إعدادات تيليجرام
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

def send_test_alert():
    current_time = datetime.now().strftime("%H:%M:%S")
    message = (
        f"🟢 **[TEST MODE] رسالة تجريبية عند بدء التشغيل والتحديث**\n\n"
        f"⚽ المباراة: **Real Madrid vs Barcelona (تجريبي)**\n"
        f"🌍 الدولة / البطولة: **الدوري الإسباني (تجريبي)**\n"
        f"⏰ وقت التحديث: `{current_time}`\n"
        f"📌 الحالة الرسمية (كووورة): انتهت المباراة (FT) ✅\n\n"
        f"⚠️ **المنصات المستهدفة للفحص السريع:**\n"
    )
    
    for bookie in TARGET_BOOKMAKERS:
        message += f"• {bookie} 🟡\n"
        
    message += f"\n⚡ **البوت يعمل الآن وجاهز لمراقبة المباريات الحقيقية بنجاح!**"
    
    send_telegram_message(message)

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
        matches = soup.find_all(['div', 'tr'], class_=lambda x: x and ('match' in x or 'game' in x))
        
        if not matches:
            matches = soup.find_all('div', text=lambda t: t and ('انتهت' in t or 'الشوط الأول' in t or 'FT' in t))

        for match in matches:
            match_text = match.get_text(separator=" ", strip=True)
            
            is_ft = 'FT' in match_text or 'انتهت' in match_text or 'نهاية المباراة' in match_text
            is_ht = 'HT' in match_text or 'الشوط الأول' in match_text
            
            if is_ft or is_ht:
                status_type = "FT" if is_ft else "HT"
                match_id = hash(match_text[:50])
                
                if match_id not in sent_alerts:
                    match_name = "مباراة رُصدت عبر النظام"
                    league = "الدوري / البطولة المتاحة"
                    
                    lines = [line.strip() for line in match_text.split('\n') if line.strip()]
                    if len(lines) >= 2:
                        match_name = f"{lines[0]} vs {lines[1]}"
                    
                    format_and_send_alert(match_name, league, status_type)
                    sent_alerts.add(match_id)
                    
                    if len(sent_alerts) > 500:
                        sent_alerts.clear()
            
    except Exception as e:
        print(f"Error scraping Kooora: {e}")

def bot_loop():
    while True:
        check_kooora_matches()
        time.sleep(60)

if __name__ == "__main__":
    # تشغيل سيرفر الفلاسك في خلفية مستقلة
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    # إرسال رسالة تجريبية فور تشغيل البوت للتأكد من الاتصال
    send_test_alert()
    
    # بدء حلقة العمل المستمرة للبوت
    bot_loop()
