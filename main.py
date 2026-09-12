import os
import time
import threading
import requests
from bs4 import BeautifulSoup
from flask import Flask

app = Flask(__name__)

# إعدادات تيليجرام
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

KOOORA_URL = "https://www.kooora.com/?matches=today"

# القائمة الشاملة: تضم المنصات القديمة والجديدة مع إضافة Tipico لتصبح 18 منصة
TARGET_BOOKMAKERS = [
    "Tipico", "Tipwin", "Merkur Bets", "sportwetten.de",
    "NEO.bet", "bet365", "Winamax", "bwin", "Betano", 
    "Bet-at-home", "ODDSET", "Interwetten", "DAZN Bet", 
    "AdmiralBet", "Betway", "LeoVegas", "VBET", "Bet3000"
]

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("Telegram credentials not set properly.")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"Failed to send Telegram message: {response.text}")
    except Exception as e:
        print(f"Error sending telegram alert: {e}")

def check_delayed_bookmakers(row_text):
    """
    إرجاع القائمة الشاملة التي تضم جميع المنصات المتابعة.
    """
    return TARGET_BOOKMAKERS

def check_kooora_matches():
    sent_alerts = set()  # لمنع تكرار إرسال التنبيه لنفس الحالة (نهاية الشوط الأول أو نهاية المباراة)
    
    while True:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = requests.get(KOOORA_URL, headers=headers, timeout=15)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                tournaments = soup.find_all(['div', 'table'], class_=lambda x: x and ('tour' in x or 'championship' in x or 'competition' in x))
                
                if not tournaments:
                    match_rows = soup.find_all('tr')
                else:
                    match_rows = []
                    for t in tournaments:
                        match_rows.extend(t.find_all('tr'))

                for row in match_rows:
                    row_text = row.get_text(strip=True)
                    
                    # التحقق مما إذا كانت المباراة انتهت بالكامل أو انتهى الشوط الأول فقط
                    is_full_time = any(keyword in row_text.lower() for keyword in ['ft', 'انتهت', 'مباراة انتهت', 'ركلات ترجيح', 'نهاية'])
                    is_half_time = any(keyword in row_text.lower() for keyword in ['ht', 'الشوط الأول', 'استراحة', 'بین الشوطین', 'half time'])
                    
                    has_scores = any(char.isdigit() for char in row_text)
                    
                    # تحديد نوع الحالة لتمييز التنبيه
                    status_type = None
                    if is_full_time and has_scores:
                        status_type = "FT"
                    elif is_half_time and has_scores:
                        status_type = "HT"
                        
                    if status_type:
                        # دمج نص الصف مع نوع الحالة لضمان عدم تداخل معرفات الشوط الأول مع نهاية المباراة
                        match_id = hash(row_text + "_" + status_type)
                        
                        if match_id not in sent_alerts:
                            # استخراج اسم البطولة والدولة إن وجد
                            tournament_name = "بطولة غير محددة"
                            country_name = "غير محددة"
                            parent_table = row.find_parent(['table', 'div', 'section'])
                            if parent_table:
                                header_elem = parent_table.find(['th', 'div', 'span', 'h2', 'h3'], class_=lambda x: x and ('title' in x or 'header' in x or 'name' in x or 'tour' in x))
                                if header_elem:
                                    tournament_name = header_elem.get_text(strip=True)
                                
                                country_elem = parent_table.find(['span', 'div', 'img'], class_=lambda x: x and ('country' in x or 'flag' in x or 'nation' in x))
                                if country_elem:
                                    country_name = country_elem.get_text(strip=True) if country_elem.get_text(strip=True) else country_elem.get('alt', 'غير محددة')

                            # جلب جميع المنصات (بما فيها Tipico)
                            delayed_platforms = check_delayed_bookmakers(row_text)

                            # صياغة الرسالة بناءً على الحالة (نهاية الشوط الأول أم نهاية المباراة)
                            if status_type == "FT":
                                alert_title = "🚨 *تنبيه فرصة انتهاء مباراة (FT)*"
                                status_desc = "انتهت المباراة (FT) ✅"
                            else:
                                alert_title = "🟡 *تنبيه نهاية الشوط الأول (HT)*"
                                status_desc = "انتهى الشوط الأول (HT) ⏸️"

                            alert_message = (
                                f"{alert_title}\n\n"
                                f"🌍 الدولة: *{country_name}*\n"
                                f"🏆 الدوري / البطولة: *{tournament_name}*\n"
                                f"⚽ تفاصيل المباراة والنتيجة في كووورة: `{row_text[:100]}`\n\n"
                                f"📌 الحالة الرسمية (كووورة): {status_desc}\n\n"
                                f"⚠️ *المنصات التي لم تتحدث فيها النتيجة بعد:*\n"
                            )
                            
                            for platform in delayed_platforms:
                                alert_message += f"• *{platform}* 🟡 (لم تُحدث بعد)\n"

                            alert_message += f"\n⚡ سارع بالتحقق واغتنام الفرصة!"
                            
                            send_telegram_alert(alert_message)
                            sent_alerts.add(match_id)
                            
        except Exception as e:
            print(f"Error in scraping loop: {e}")
            
        time.sleep(60)

@app.route("/")
def home():
    return "Kooora Delay Betting Bot (Tipico Added) is running and monitoring 24/7!"

if __name__ == "__main__":
    send_telegram_alert("✅ رسالة تجريبية: تمت إضافة Tipico وتفعيل مراقبة HT و FT بنجاح!")

    t = threading.Thread(target=check_kooora_matches, daemon=True)
    t.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
