import os
import time
import threading
import requests
from bs4 import BeautifulSoup
from flask import Flask

app = Flask(__name__)

# إعدادات تيليجرام (تأكد من صحة المتغيرات البيئية في Render أو ضعها مباشرة هنا)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

KOOORA_URL = "https://www.kooora.com/?matches=today"

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
                
                # البحث عن المباريات في الصفحة (تختلف الهيكلة حسب تحديث الموقع، وغالباً تكون مقسمة حسب البطولات)
                # سنبحث عن عناصر البطولات والمباريات ضمنها
                match_blocks = soup.find_all(['tr', 'div'], class_=lambda x: x and ('match' in x or 'game' in x or 'torne' in x))
                
                # طريقة بديلة وشاملة للبحث عن البطولات والمباريات
                tournaments = soup.find_all(['div', 'table'], class_=lambda x: x and ('tour' in x or 'championship' in x or 'competition' in x))
                
                if not tournaments:
                    # إذا لميل العثور على حاويات بطولات محددة، نبحث عن جميع عناصر المباريات المباشرة
                    match_rows = soup.find_all('tr')
                else:
                    match_rows = []
                    for t in tournaments:
                        match_rows.extend(t.find_all('tr'))

                for row in match_rows:
                    row_text = row.get_text(strip=True)
                    
                    # التحقق من أن الصف يمثل مباراة منتهية (يحتوي على مؤشر انتهاء مثل FT، انتهت، أو نتيجة رقمية مع علامة انتهاء)
                    is_finished = any(keyword in row_text.lower() for keyword in ['ft', 'انتهت', 'مباراة انتهت', 'ركلات ترجيح', 'نهاية'])
                    
                    # استبعاد الأخبار والعناوين التي لا تحتوي على أرفاق فرق أو نتائج
                    has_scores = any(char.isdigit() for char in row_text)
                    
                    if is_finished and has_scores:
                        match_id = hash(row_text)
                        if match_id not in sent_alerts:
                            # محاولة استخراج اسم البطولة أو الدوري المحيط بالمباراة
                            tournament_name = "بطولة غير محددة"
                            parent_table = row.find_parent(['table', 'div', 'section'])
                            if parent_table:
                                header_elem = parent_table.find(['th', 'div', 'span', 'h2', 'h3'], class_=lambda x: x and ('title' in x or 'header' in x or 'name' in x or 'tour' in x))
                                if header_elem:
                                    tournament_name = header_elem.get_text(strip=True)

                            # تنسيق رسالة التنبيه الجديدة مع تفاصيل الدوري
                            alert_message = (
                                f"🚨 *تنبيه فجوة تأخير عاجل!*\n\n"
                                f"🏆 البطولة: *{tournament_name}*\n"
                                f"المباراة والنطاق: `{row_text[:100]}`\n\n"
                                f"🛑 الحالة في المصدر الرسمي (كووورة): انتهت تماماً\n"
                                f"⏳ الحالة في المنصة (Tipwin / Merkur Bets / sportwetten.de): لا تزال معروضة أو متاحة للرهان!\n\n"
                                f"⚡ سارع بالتحقق واغتنام الفرصة!"
                            )
                            
                            send_telegram_alert(alert_message)
                            sent_alerts.add(match_id)
                            
        except Exception as e:
            print(f"Error in scraping loop: {e}")
            
        # الانتظار 60 ثانية قبل إعادة الفحص لتجنب الحظر ولضمان السرعة
        time.sleep(60)

@app.route("/")
def home():
    return "Kooora Delay Betting Bot is running and monitoring 24/7!"

if __name__ == "__main__":
    # تشغيل مراقبة المباريات في خلفية مستقلة لتعمل بالتوازي مع سيرفر الويب
    t = threading.Thread(target=check_kooora_matches, daemon=True)
    t.start()
    
    # تشغيل تطبيق Flask
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
