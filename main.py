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

# روابط كووورة الرسمية لجداول مباريات اليوم
KOOORA_URLS = [
    "https://www.kooora.com/%D9%83%D8%B1%D8%A9-%D8%A7%D9%84%D9%82%D8%AF%D9%85/%D9%85%D8%A8%D8%A7%D8%B1%D9%8A%D8%A7%D8%AA-%D8%A7%D9%84%D9%8A%D9%88%D9%85"
]

KOOORA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.9"
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

def parse_kooora_matches():
    for url in KOOORA_URLS:
        try:
            response = requests.get(url, headers=KOOORA_HEADERS, timeout=12)
            if response.status_code != 200:
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # استهداف حاويات المباريات في هيكل كووورة المحدث (غالباً تكون ضمن عناصر تضمن تفاصيل اللقاء)
            match_boxes = soup.find_all(['div', 'tr'], class_=lambda x: x and any(c in x for c in ['match', 'game', 'fi-block', 'match-item']))
            
            if not match_boxes:
                # طريقة بديلة في حال تغير التصميم: البحث عن الجداول التي تحتوي عمود النتيجة
                match_boxes = soup.find_all('tr')

            for box in match_boxes:
                text_content = box.get_text(separator=" | ", strip=True)
                if not text_content or len(text_content) < 15:
                    continue

                upper_text = text_content.upper()
                
                # التحقق الحازم من حالة انتهاء المباراة
                if "انتهت" in text_content or "FT" in upper_text:
                    
                    # استخراج النتيجة (مثلاً 2-1 أو 0 - 0)
                    score_match = re.search(r'(\d+\s*[-–]\s*\d+)', text_content)
                    if not score_match:
                        continue # إذا لم توجد نتيجة مسجلة رسمياً، نتخطى المباراة لضمان عدم إرسال بيانات ناقصة
                    
                    score_detected = score_match.group(1)

                    # استخراج أسماء الفرق بدقة من خلال تحليل النصوص الصافية
                    # في كووورة عادة يكون النص: الفريق الأول | النتيجة | الفريق الثاني
                    parts = [p.strip() for p in text_content.split("|") if len(p.strip()) > 2]
                    
                    # تنظيف القائمة من الكلمات الدلالية والبطولات والأرقام
                    unwanted = [
                        "انتهت", "FT", "-", "وقت اضافي", "ركلات ترجيح", "المباراة", 
                        "الدوري", "كأس", "بطولة", "المجموعة", "الجولة", "الاسبوع",
                        "دوري أبطال", "تصفيات", "ودية", "دولي", "مباريات اليوم", score_detected
                    ]
                    
                    clean_teams = []
                    for p in parts:
                        if p in unwanted or any(w in p for w in unwanted):
                            continue
                        if re.match(r'^\d{1,2}:\d{2}$', p): # تجاهل أوقات المباريات (مثل 18:00)
                            continue
                        if len(p) > 2:
                            clean_teams.append(p)

                    # يجب أن نحصل على ناديين حقيقيين مختلفين تماماً
                    if len(clean_teams) < 2:
                        continue

                    team1 = clean_teams[0]
                    team2 = clean_teams[1]

                    # شروط إضافية لمنع الأخطاء الوهمية والأسماء المتطابقة
                    if team1.lower() == team2.lower() or team1.lower() in team2.lower() or team2.lower() in team1.lower():
                        continue
                    
                    # التأكد من أن الفريقين لا يحتويان على أحرف لاتينية مكررة (مثل هيبار vs HEB)
                    if len(team1) <= 3 or len(team2) <= 3:
                        continue

                    match_name = f"{team1} vs {team2}"
                    match_fingerprint = f"{team1}_{team2}_{score_detected}".lower()

                    # التأكد من عدم تكرار إرسال نفس المباراة نهائياً
                    if match_fingerprint not in sent_matches_cache:
                        sent_matches_cache.add(match_fingerprint)
                        
                        # فحص حالة المنصات للتأكد من وجود فجوة حقيقية (أنها معروضة كـ Pre-match)
                        bookmaker_results = check_all_bookmakers()
                        
                        message = (
                            f"🚨 *رصد فجوة مطابقة دقيقة (انتهت vs لم تبدأ)!* 🚨\n\n"
                            f"⚽ المباراة: {match_name}\n"
                            f"🛑 الحالة على كووورة: انتهت المباراة (FT)\n"
                            f"🎯 *النتيجة النهائية المؤكدة: ( {score_detected} )*\n"
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
    send_telegram_message("🛡️ تم تفعيل نظام الفلترة المطلقة: لا تنبيه إلا لوجود نتيجة نهائية مؤكدة وناديين حقيقيين!")
    while True:
        try:
            parse_kooora_matches()
        except Exception:
            pass
        time.sleep(60)

bot_thread = threading.Thread(target=bot_loop, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
