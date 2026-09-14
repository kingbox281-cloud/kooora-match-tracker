import os
import time
import threading
import requests
from datetime import datetime
from flask import Flask
from bs4 import BeautifulSoup

# =========================================================
# FLASK / RENDER
# =========================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running and monitoring Kooora matches 24/7!"

@app.route("/health")
def health():
    return "OK"

# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("Telegram token is not configured.")
        return None

    if not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID":
        print("Telegram chat ID is not configured.")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
        print("Telegram:", response.status_code)
        return response.json()
    except Exception as e:
        print(f"Telegram error: {e}")
        return None

# =========================================================
# KOOORA
# =========================================================

KOOORA_URLS = [
    "https://www.kooora.com/%D9%83%D8%B1%D8%A9-%D8%A7%D9%84%D9%82%D8%AF%D9%85/%D9%85%D8%A8%D8%A7%D8%B1%D9%8A%D8%A7%D8%AA-%D8%A7%D9%84%D9%8A%D9%88%D9%85",
    "https://www.kooora.com/default.aspx?g=matches"
]

KOOORA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.8"
}

# =========================================================
# 18 GERMAN BOOKMAKERS
# =========================================================

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

CAPTCHA_WORDS = [
    "captcha", "recaptcha", "hcaptcha", "verify you are human", 
    "verify that you are human", "are you human", "security check", 
    "bot detection", "access denied", "cloudflare"
]

def detect_captcha(response):
    text = response.text.lower()
    for word in CAPTCHA_WORDS:
        if word in text:
            return True
    
    server_text = (str(response.headers.get("server", "")) + " " +
                   str(response.headers.get("cf-ray", "")) + " " +
                   str(response.headers.get("cf-mitigated", ""))).lower()
    for word in CAPTCHA_WORDS:
        if word in server_text:
            return True
    return False

def check_bookmaker_access(bookmaker):
    url = BOOKMAKER_URLS.get(bookmaker)
    if not url:
        return "NOT_CHECKED"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        if detect_captcha(response):
            return "CAPTCHA"
        if response.status_code in [401, 403, 429]:
            return "BLOCKED"
        if response.status_code >= 500:
            return "SERVER_ERROR"
        if response.status_code == 200:
            return "ACCESSIBLE"
        return "NOT_CHECKED"
    except Exception:
        return "ERROR"

def check_all_bookmakers():
    results = {}
    for bookmaker in TARGET_BOOKMAKERS:
        results[bookmaker] = check_bookmaker_access(bookmaker)
        time.sleep(0.3)
    return results

def bookmaker_status_icon(status):
    if status == "ACCESSIBLE":
        return "🟢 يمكن الوصول للصفحة"
    if status == "CAPTCHA":
        return "🚫 CAPTCHA - تم الاستبعاد"
    if status == "BLOCKED":
        return "🔴 الوصول محظور"
    if status == "TIMEOUT":
        return "🟠 Timeout"
    if status == "SERVER_ERROR":
        return "🟠 خطأ في الخادم"
    if status == "ERROR":
        return "🔴 خطأ اتصال"
    return "⚪ لم يتم التحقق"

# =========================================================
# ALERTS
# =========================================================

sent_alerts = set()

def format_and_send_alert(match_name, country, league, status_type):
    current_time = datetime.now().strftime("%H:%M:%S")
    
    if status_type == "FT":
        status_text = "انتهت المباراة تماماً (FT) ✅"
        title = "🚨 تنبيه: نهاية المباراة على كووورة"
    else:
        status_text = "انتهى الشوط الأول (HT) ⏸️"
        title = "🟡 تنبيه: نهاية الشوط الأول على كووورة"

    bookmaker_results = check_all_bookmakers()

    message = (
        f"{title}\n\n"
        f"⚽ المباراة: {match_name}\n"
        f"🌍 الدولة: {country}\n"
        f"🏆 البطولة: {league}\n"
        f"⏰ وقت التحديث: {current_time}\n\n"
        f"🛑 حالة كووورة:\n{status_text}\n\n"
        f"📊 حالة الوصول إلى المنصات:\n\n"
    )

    accessible, captcha, blocked, other = 0, 0, 0, 0

    for bookmaker in TARGET_BOOKMAKERS:
        status = bookmaker_results.get(bookmaker, "NOT_CHECKED")
        icon = bookmaker_status_icon(status)
        message += f"• {bookmaker}: {icon}\n"

        if status == "ACCESSIBLE":
            accessible += 1
        elif status == "CAPTCHA":
            captcha += 1
        elif status == "BLOCKED":
            blocked += 1
        else:
            other += 1

    message += (
        "\n📌 الملخص:\n"
        f"🟢 صفحات متاحة: {accessible}\n"
        f"🚫 CAPTCHA: {captcha}\n"
        f"🔴 محظورة: {blocked}\n"
        f"⚪ أخرى: {other}"
    )

    send_telegram_message(message)

# =========================================================
# PARSER
# =========================================================

def get_kooora_page():
    for url in KOOORA_URLS:
        try:
            response = requests.get(url, headers=KOOORA_HEADERS, timeout=20)
            if response.status_code == 200:
                return response
        except Exception:
            pass
    return None

def extract_match_name(text):
    ignored = {"انتهت", "FT", "HT", "الشوط", "الأول", "المباراة", "الدوري", "كأس"}
    words = [w.strip() for w in text.split() if len(w.strip()) > 1 and w.strip() not in ignored and not w.strip().isdigit()]
    if len(words) >= 2:
        return f"{words[0]} vs {words[1]}"
    return "مباراة مرصودة"

def detect_status(text):
    upper_text = text.upper()
    if "انتهت" in text or "FT" in upper_text:
        return "FT"
    if "الشوط الأول" in text or "HT" in upper_text:
        return "HT"
    return None

def check_kooora_matches():
    response = get_kooora_page()
    if response is None:
        return

    try:
        soup = BeautifulSoup(response.text, "html.parser")
        current_league = "الدوري العام"
        current_country = "الدولي / محلي"
        
        matches = soup.find_all("tr")
        if not matches:
            matches = soup.find_all("div", class_="match")

        for match in matches:
            text = match.get_text(separator=" ", strip=True)
            if not text:
                continue

            if any(k in text for k in ["الدوري", "دوري", "كأس", "بطولة"]):
                parts = [p.strip() for p in text.split("-") if len(p.strip()) > 3]
                if parts:
                    current_league = parts[0][:60]

            status_detected = detect_status(text)
            if not status_detected:
                continue

            match_name = extract_match_name(text)
            match_id = f"{match_name}|{current_league}|{status_detected}"

            if match_id in sent_alerts:
                continue

            format_and_send_alert(match_name, current_country, current_league, status_detected)
            sent_alerts.add(match_id)

            if len(sent_alerts) > 1000:
                sent_alerts.clear()

    except Exception as e:
        print(f"Scraping error: {e}")

# =========================================================
# LOOP & START
# =========================================================

def bot_loop():
    send_telegram_message("🚀 تم تشغيل نظام مراقبة مباريات كووورة والمنصات بنجاح 24/7!")
    while True:
        try:
            check_kooora_matches()
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(60)

bot_thread = threading.Thread(target=bot_loop, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
