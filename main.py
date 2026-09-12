import os
import time
import threading
import requests
from datetime import datetime
from flask import Flask
from bs4 import BeautifulSoup

app = Flask('')

@app.route('/')
def home():
    return "Bot is running and monitoring Kooora 24/7!"

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', 'YOUR_CHAT_ID')

KOOORA_URL = "https://www.kooora.com/?matches=today"

TARGET_BOOKMAKERS = [
    "Tipico", "Tipwin", "Merkur Bets", "sportwetten.de", "NEO.bet", 
    "bet365", "Winamax", "bwin", "Betano", "Bet-at-home", 
    "ODDSET", "Interwetten", "DAZN Bet", "AdmiralBet", "Betway", 
    "LeoVegas", "VBET", "Bet3000"
]

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

def format_and_send_alert(match_name, country, league, status_type):
    current_time = datetime.now().strftime("%H:%M:%S")
    
    if status_type == "FT":
        status_text = "انتهت المباراة تماماً (FT) ✅"
        title = "🚨 تنبيه فجوة تأخير عاجل!"
    else:
        status_text = "انتهى الشوط الأول ⏸️"
        title = "🟡 تنبيه فجوة تأخير الشوط الأول!"
        
    message = (
        f"{title}\n\n"
        f"⚽ المباراة: **{match_name}**\n"
        f"🌍 الدولة: **{country}**\n"
        f"🏆 البطولة: ****\n"
        f"⏰ وقت التحديث: `{current_time}`\n"
        f"🛑 الحالة في المصدر الرسمي (كووورة): {status_text}\n"
        f"⏳ الحالة في المنصات: **لا تزال معروضة أو لم يتم إيقاف الرهان بعد في المنصات المستهدفة أدناه!**\n\n"
        f"⚠️ **المنصات للفحص السريع:**\n"
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
        print(f"Kooora response status: {response.status_code}")
        
        # رسالة تأكيد تصلك على التيليجرام في كل عملية فحص دورية لتطمئن أن البوت يعيثث ويحدث
        current_time = datetime.now().strftime("%H:%M:%S")
        send_telegram_message(f"🔄 البوت قام بعملية فحص حديثة لموقع كووورة بنجاح في الساعة `{current_time}` وحالة الاتصال: `{response.status_code}`")
        
        if response.status_code != 200:
            return
        
        soup = BeautifulSoup(response.text, 'html.parser')
        current_league = "بطولة عامة"
        current_country = "الدولي / محلي"
        
        for element in soup.find_all(['div', 'section', 'table']):
            text = element.get_text(separator=" ", strip=True)
            if 'الدوري' in text or 'كأس' in text or 'بطولة' in text:
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                if lines and len(lines[0]) < 40:
                    current_league = lines[0]
            
            if 'انتهت' in text or 'FT' in text:
                match_id = hash(text[:60])
                if match_id not in sent_alerts:
                    match_name = "مباراة مرصودة"
                    lines = [l for l in text.split() if len(l) > 2]
                    if len(lines) >= 2:
                        match_name = f"{lines[0]} vs {lines[1]}"
                    
                    format_and_send_alert(match_name, current_country, current_league, "FT")
                    sent_alerts.add(match_id)
                    
                    if len(sent_alerts) > 500:
                        sent_alerts.clear()
    except Exception as e:
        print(f"Error scraping Kooora: {e}")

def bot_loop():
    while True:
        print("Checking Kooora matches...")
        check_kooora_matches()
        time.sleep(60)

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
