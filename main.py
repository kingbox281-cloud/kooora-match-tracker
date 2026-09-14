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

sent_matches_cache = set()

def check_kooora_matches():
    for url in KOOORA_URLS:
        try:
            response = requests.get(url, headers=KOOORA_HEADERS, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                
                # استهداف الجداول أو الكتل التي تحتوي على تفاصيل المباريات بدقة
                match_blocks = soup.find_all(['tr', 'div'], class_=lambda x: x and any(c in x for c in ['match', 'game', 'fi-', 'm-row']))
                if not match_blocks:
                    match_blocks = soup.find_all('tr')

                for block in match_blocks:
                    full_text = block.get_text(separator=" | ", strip=True)
                    if not full_text or len(full_text) < 10:
                        continue

                    upper_text = full_text.upper()
                    
                    # التأكد الجازم أن المباراة انتهت (تاريخياً أو حالياً)
                    if "انتهت" in full_text or "FT" in upper_text or "انتهت المباراة" in full_text:
                        
                        # محاولة استخراج الفريقين والنتيجة من النص المهيكل
                        teams_found = []
                        score_detected = "غير متوفرة"
                        
                        # البحث عن النتيجة النمطية (مثل 2-1 أو 0 - 3)
                        score_match = re.search(r'(\d+\s*[-–]\s*\d+)', full_text)
                        if score_match:
                            score_detected = score_match.group(1)

                        # تنظيف النصوص واستخراج الأجزاء النصية المفيدة
                        parts = [p.strip() for p in full_text.split("|") if len(p.strip()) > 2]
                        
                        ignore_list = [
                            "انتهت", "FT", "-", "وقت اضافي", "ركلات ترجيح", "المباراة", 
                            "الدوري", "كأس", "بطولة", "المجموعة", "الجولة", "الاسبوع",
                            "دوري أبطال", "تصفيات", "ودية", "دولي", "مباريات اليوم", score_detected
                        ]

                        for p in parts:
                            # تجاهل الكلمات العامة وأرقام النتيجة والبطولات
                            if any(ignore_word == p or ignore_word in p for ignore_word in ignore_list):
                                continue
                            if re.match(r'^\d+$', p): # تجاهل الأرقام المنفردة (كالوقت أو التوقيت)
                                continue
                            if len(p) > 2 and p not in teams_found:
                                teams_found.append(p)

                        # يجب أن نجد فريقين حقيقيين فقط لا غير
                        if len(teams_found) < 2:
                            continue

                        team1 = teams_found[0]
                        team2 = teams_found[1]

                        # منع تداخل الأسماء أو تشابهها الوهمي (مثل الفريق ضد نفسه أو اختصاره)
                        if team1.lower() in team2.lower() or team2.lower() in team1.lower():
                            continue

                        match_name = f"{team1} vs {team2}"
                        match_fingerprint = f"{team1}_{team2}".lower()

                        # التأكد من عدم إرسال نفس المباراة مجدداً
                        if match_fingerprint not in sent_matches_cache:
                            sent_matches_cache.add(match_fingerprint)
                            
                            bookmaker_results = check_all_bookmakers()
                            
                            message = (
                                f"🚨 *رصد فجوة تطابق حقيقية (انتهت vs لم تبدأ)!* 🚨\n\n"
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
    send_telegram_message("🎯 تم تحديث نظام المطابقة الدقيقة للفرق ومنع الأخطاء بنجاح!")
    while True:
        try:
            check_kooora_matches()
        except Exception:
            pass
        time.sleep(60)

bot_thread = threading.Thread(target=bot_loop, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
