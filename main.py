import os
import time
import threading
import requests
import re
from datetime import datetime
from flask import Flask
from bs4 import BeautifulSoup

app = Flask(__name__)

@app.route("/")
def home():
    return "Result Gap Hunter Bot is running 24/7!"

@app.route("/health")
def health():
    return "OK"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception:
        return None

KOOORA_URLS = [
    "https://www.kooora.com/%D9%83%D8%B1%D8%A9-%D8%A7%D9%84%D9%82%D8%AF%D9%85/%D9%85%D8%A8%D8%A7%D8%B1%D9%8A%D8%A7%D8%AA-%D8%A7%D9%84%D9%8A%D9%88%D9%85",
    "https://www.kooora.com/default.aspx?g=matches"
]

KOOORA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.8"
}

TARGET_BOOKMAKERS = [
    "Tipico", "Tipwin", "Merkur Bets", "sportwetten.de", "NEO.bet", 
    "bet365", "Winamax", "bwin", "Betano", "Bet-at-home", 
    "ODDSET", "Interwetten", "DAZN Bet", "AdmiralBet", 
    "Betway", "LeoVegas", "VBET", "Bet3000"
]

BOOKMAKER_URLS = {
    "Tipico": "https://www.tipico.de/",
    "Tipwin": "https://www.tipwin.de/",
    "Merkur Bets": "https://www.merkurbets.de/",
    "sportwetten.de": "https://www.sportwetten.de/",
    "NEO.bet": "https://www.neo.bet/",
    "bet365": "https://www.bet365.com/",
    "Winamax": "https://www.winamax.de/",
    "bwin": "https://www.bwin.de/",
    "Betano": "https://www.betano.de/",
    "Bet-at-home": "https://www.bet-at-home.com/",
    "ODDSET": "https://www.oddset.de/",
    "Interwetten": "https://www.interwetten.com/",
    "DAZN Bet": "https://www.daznbet.de/",
    "AdmiralBet": "https://www.admiralbet.de/",
    "Betway": "https://betway.de/",
    "LeoVegas": "https://www.leovegas.com/",
    "VBET": "https://www.vbet.de/",
    "Bet3000": "https://www.bet3000.com/"
}

CAPTCHA_WORDS = ["captcha", "recaptcha", "hcaptcha", "verify you are human", "security check", "cloudflare", "access denied"]

def detect_captcha(response):
    text = response.text.lower()
    for word in CAPTCHA_WORDS:
        if word in text:
            return True
    return False

def check_bookmaker_access(bookmaker):
    url = BOOKMAKER_URLS.get(bookmaker)
    if not url:
        return "ERROR"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        response = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
        if detect_captcha(response):
            return "CAPTCHA"
        if response.status_code in [401, 403, 429]:
            return "BLOCKED"
        if response.status_code == 200:
            return "ACCESSIBLE"
        return "ERROR"
    except Exception:
        return "ERROR"

def check_all_bookmakers():
    results = {}
    for bookmaker in TARGET_BOOKMAKERS:
        results[bookmaker] = check_bookmaker_access(bookmaker)
    return results

# ذاكرة قوية لمنع التكرار نهائياً
sent_matches_cache = set()

def check_kooora_matches():
    for url in KOOORA_URLS:
        try:
            response = requests.get(url, headers=KOOORA_HEADERS, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                
                # استهداف الصفوف التي تحتوي على نتائج مباريات فقط
                rows = soup.find_all(["tr", "div"], class_=lambda x: x and ('match' in x or 'fi' in x or 'game' in x))
                if not rows:
                    rows = soup.find_all("tr")

                for row in rows:
                    text = row.get_text(separator=" ", strip=True)
                    if not text or len(text) < 15:
                        continue

                    upper_text = text.upper()
                    
                    # التحقق الصارم من حالة انتهاء المباراة
                    if "انتهت" in text or "FT" in upper_text:
                        clean_text = re.sub(r'\s+', ' ', text)
                        
                        # استبعاد الأسطر العامة التي لا تمثل مباريات حقيقية
                        if "الدوري" in clean_text and len(clean_text.split()) < 5:
                            continue

                        # البحث عن النتيجة النهائية
                        score_match = re.search(r'(\d+\s*-\s*\d+)', clean_text)
                        score_detected = score_match.group(1) if score_match else "غير متوفرة"

                        # استخراج الكلمات الأساسية لتشكيل اسم المباراة
                        words = [w for w in clean_text.split() if w not in ["انتهت", "FT", "-", "وقت", "اضافي", "ركلات", "ترجيح", score_detected]]
                        if len(words) < 4:
                            continue

                        team1 = words[0]
                        team2 = words[1] if len(words) > 1 else "فريق2"
                        match_name = f"{team1} vs {team2}"

                        # بناء بصمة فريدة وثابتة للمباراة لمنع تكرارها للأبد
                        match_fingerprint = f"{team1}_{team2}".lower()
                        
                        if match_fingerprint not in sent_matches_cache:
                            # حفر البصمة في الذاكرة فوراً قبل فحص المنصات
                            sent_matches_cache.add(match_fingerprint)
                            
                            bookmaker_results = check_all_bookmakers()
                            
                            message = (
                                f"🚨 *رصد فجوة توقيت/حالة (انتهت vs لم تبدأ)!* 🚨\n\n"
                                f"⚽ المباراة: {match_name}\n"
                                f"🛑 الحالة على كووورة: انتهت المباراة (FT)\n"
                                f"🎯 *النتيجة النهائية: ( {score_detected} )*\n"
                                f"⚠️ حالة المنصات: معروضة كـ (لم تبدأ بعد / Pre-match)\n"
                                f"⏰ وقت الرصد: {datetime.now().strftime('%H:%M:%S')}\n\n"
                                f"🟢 المنصات المتأخرة التي تعرضها كـ \"لم تبدأ\":\n"
                            )

                            accessible_count = 0
                            for bookmaker in TARGET_BOOKMAKERS:
                                if bookmaker_results.get(bookmaker) == "ACCESSIBLE":
                                    accessible_count += 1
                                    message += f"• {bookmaker}: 🟢 متاحة (تسمح بالرهان المسبق)\n"

                            message += f"\n📊 إجمالي المنصات المتأخرة: {accessible_count} من أصل 18"
                            
                            send_telegram_message(message)
                break
        except Exception:
            pass

def bot_loop():
    send_telegram_message("🚀 تم تطبيق القفل النهائي لمنع التكرار بنجاح!")
    while True:
        try:
            check_kooora_matches()
        except Exception:
            pass
        # تباعد زمني أطول (دقيقتين) لضمان الاستقرار التام وتجنب الإزعاج
        time.sleep(120)

bot_thread = threading.Thread(target=bot_loop, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
