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

# قائمة المنصات الموسعة التي طلبته إضافتها
TARGET_BOOKMAKERS = [
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
    ملاحظة: يمكنك ربط هذه الدالة لاحقاً بالفحص الفعلي لكل منصة.
    حسب رغبتك، سيقوم البوت بتحديد المنصات التي لم تبدأ فيها المباراة بعد.
    في هذا المثال التوضيحي، نقوم بفلترة محاكاة أو يمكنك ربطها بـ API الفحص الخاص بك.
    """
    # كمثال مبدئي، سنقوم بتضمين القائمة التي لم تبدأ بعد عندما تنتهي المباراة في كووورة
    # يمكنك تعديل هذا الجزء ليطابق طريقة جلب البيانات الفعلية لكل منصة من المنصات التالية:
    return TARGET_BOOKMAKERS

def check_kooora_matches():
    sent_alerts = set()  # لمنع تكرار إرسال التنبيه لنفس المباراة
    
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
                    
                    is_finished = any(keyword in row_text.lower() for keyword in ['ft', 'انتهت', 'مباراة انتهت', 'ركلات ترجيح', 'نهاية'])
                    has_scores = any(char.isdigit() for char in row_text)
                    
                    if is_finished and has_scores:
                        match_id = hash(row_text)
                        if match_id not in sent_alerts:
                            # استخراج اسم البطولة والدولة إن وجد
                            tournament_name = "بطولة غير محددة"
                            country_name = "غير محددة"
                            parent_table = row.find_parent(['table', 'div', 'section'])
                            if parent_table:
                                header_elem = parent_table.find(['th', 'div', 'span', 'h2', 'h3'], class_=lambda x: x and ('title' in x or 'header' in x or 'name' in x or 'tour' in x))
                                if header_elem:
                                    tournament_name = header_elem.get_text(strip=True)
                                
                                # محاولة البحث عن اسم الدولة من الحاوية المحيطة
                                country_elem = parent_table.find(['span', 'div', 'img'], class_=lambda x: x and ('country' in x or 'flag' in x or 'nation' in x))
                                if country_elem:
                                    country_name = country_elem.get_text(strip=True) if country_elem.get_text(strip=True) else country_elem.get('alt', 'غير محددة')

                            # جلب المنصات التي لم تبدأ بعد بناءً على القائمة الموسعة
                            delayed_platforms = check_delayed_bookmakers(row_text)

                            # بناء رسالة تيليجرام بالشكل الذي حددته
                            alert_message = (
                                f"🚨 *تنبيه فرصة انتهاء مباراة (FT)*\n\n"
                                f"🌍 الدولة: *{country_name}*\n"
                                f"🏆 الدوري / البطولة: *{tournament_name}*\n"
                                f"⚽ تفاصيل المباراة والنتيجة في كووورة: `{row_text[:100]}`\n\n"
                                f"📌 الحالة الرسمية (كووورة): انتهت المباراة (FT) ✅\n\n"
                                f"⚠️ *المنصات التي لم تبدأ فيها المباراة بعد:*\n"
                            )
                            
                            for platform in delayed_platforms:
                                alert_message += f"• *{platform}* 🟡 (لم تبدأ بعد)\n"

                            alert_message += f"\n⚡ سارع بالتحقق واغتنام الفرصة!"
                            
                            send_telegram_alert(alert_message)
                            sent_alerts.add(match_id)
                            
        except Exception as e:
            print(f"Error in scraping loop: {e}")
            
        time.sleep(60)

@app.route("/")
def home():
    return "Kooora Delay Betting Bot is running and monitoring 24/7!"

if __name__ == "__main__":
    send_telegram_alert("✅ رسالة تجريبية: تم تحديث البوت وإضافة القائمة الموسعة للمنصات بنجاح!")

    t = threading.Thread(target=check_kooora_matches, daemon=True)
    t.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
