import os
import time
import threading
import re
import requests
from datetime import datetime
from flask import Flask
from bs4 import BeautifulSoup

app = Flask(__name__)

# =========================================================
# FLASK
# =========================================================

@app.route("/")
def home():
    return "Bot is running and monitoring Kooora 24/7!"


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
        print("Telegram token is not configured.", flush=True)
        return None

    if not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID":
        print("Telegram chat ID is not configured.", flush=True)
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=15,
        )
        print(f"Telegram: {response.status_code}", flush=True)
        try:
            return response.json()
        except Exception:
            return {"status_code": response.status_code}
    except Exception as e:
        print(f"Telegram error: {e}", flush=True)
        return None


# =========================================================
# KOOORA - TODAY'S MATCHES
# =========================================================

KOOORA_URL = (
    "https://www.kooora.com/%D9%83%D8%B1%D8%A9-%D8%A7%D9%84%D9%82%D8%AF%D9%85/"
    "%D9%85%D8%A8%D8%A7%D8%B1%D9%8A%D8%A7%D8%AA-%D8%A7%D9%84%D9%8A%D9%88%D9%85"
)

KOOORA_FALLBACK_URL = "https://www.kooora.com/default.aspx?g=matches"

KOOORA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ar,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://www.kooora.com/",
}


# =========================================================
# BOOKMAKERS
# =========================================================

TARGET_BOOKMAKERS = [
    "Tipico", "Tipwin", "Merkur Bets", "sportwetten.de", "NEO.bet",
    "bet365", "Winamax", "bwin", "Betano", "Bet-at-home", "ODDSET",
    "Interwetten", "DAZN Bet", "AdmiralBet", "Betway", "LeoVegas",
    "VBET", "Bet3000",
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
    "Bet3000": "https://www.bet3000.com/",
}

CAPTCHA_WORDS = [
    "captcha", "recaptcha", "hcaptcha", "verify you are human",
    "verify that you are human", "are you human", "security check",
    "bot detection", "access denied", "cloudflare",
]


def detect_captcha(response):
    text = response.text.lower()
    if any(word in text for word in CAPTCHA_WORDS):
        return True

    server_text = (
        str(response.headers.get("server", "")) + " "
        + str(response.headers.get("cf-ray", "")) + " "
        + str(response.headers.get("cf-mitigated", ""))
    ).lower()
    return any(word in server_text for word in CAPTCHA_WORDS)


def check_bookmaker_access(bookmaker):
    url = BOOKMAKER_URLS.get(bookmaker)
    if not url:
        return "NOT_CHECKED"

    headers = {
        "User-Agent": KOOORA_HEADERS["User-Agent"],
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=10,
            allow_redirects=True,
        )

        print(
            f"{bookmaker}: HTTP {response.status_code} {response.url}",
            flush=True,
        )

        if detect_captcha(response):
            return "CAPTCHA"
        if response.status_code in [401, 403, 429]:
            return "BLOCKED"
        if response.status_code >= 500:
            return "SERVER_ERROR"
        if response.status_code == 200:
            return "ACCESSIBLE"
        return "NOT_CHECKED"

    except requests.exceptions.Timeout:
        print(f"{bookmaker}: timeout", flush=True)
        return "TIMEOUT"
    except requests.exceptions.RequestException as e:
        print(f"{bookmaker}: {e}", flush=True)
        return "ERROR"
    except Exception as e:
        print(f"{bookmaker}: unexpected error: {e}", flush=True)
        return "ERROR"


def check_all_bookmakers():
    results = {}
    for bookmaker in TARGET_BOOKMAKERS:
        status = check_bookmaker_access(bookmaker)
        results[bookmaker] = status
        if status == "CAPTCHA":
            print(f"CAPTCHA: {bookmaker} - skipped", flush=True)
        time.sleep(0.5)
    return results


def bookmaker_status_icon(status):
    icons = {
        "ACCESSIBLE": "🟢 يمكن الوصول للصفحة",
        "CAPTCHA": "🚫 CAPTCHA - تم الاستبعاد",
        "BLOCKED": "🔴 الوصول محظور",
        "TIMEOUT": "🟠 Timeout",
        "SERVER_ERROR": "🟠 خطأ في الخادم",
        "ERROR": "🔴 خطأ اتصال",
        "NOT_CHECKED": "⚪ لم يتم التحقق",
    }
    return icons.get(status, "⚪ لم يتم التحقق")


# =========================================================
# MEMORY
# =========================================================

# Prevents duplicate HT/FT notifications.
# The date is included so the same teams can be monitored again tomorrow.
sent_alerts = set()


# =========================================================
# TEXT HELPERS
# =========================================================

def clean_text(text):
    if not text:
        return ""

    text = str(text).replace("\xa0", " ")
    text = text.replace("\\u00a0", " ")
    text = text.replace("\\/", "/")

    translation = str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789",
    )
    text = text.translate(translation)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


FT_RE = re.compile(
    r"انتهت|إنتهت|النهاية|نهاية المباراة|\bFT\b|FULL[\s_-]*TIME",
    re.IGNORECASE,
)

HT_RE = re.compile(
    r"استراحة|نهاية الشوط|الشوط الأول|الشوط الاول|بين الشوطين|\bHT\b|HALF[\s_-]*TIME",
    re.IGNORECASE,
)

SINGLE_SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")


# =========================================================
# KOOORA COMPETITION CONTEXT
# =========================================================

def extract_competition_context(match_element):
    result = {"country": "الدولي / محلي", "league": "الدوري العام", "round": None}

    section = None
    parent = match_element.parent

    for _ in range(10):
        if parent is None:
            break
        classes = " ".join(parent.get("class", []))
        if "match-list_livescores-match-list__section" in classes:
            section = parent
            break
        parent = parent.parent

    if section is None:
        return result

    text = clean_text(section.get_text(" ", strip=True))

    round_match = re.search(r"الجولة\s*[:\-]?\s*(\d+)", text, re.I)
    if round_match:
        result["round"] = f"الجولة {round_match.group(1)}"
        prefix = text[:round_match.start()].strip()
    else:
        prefix = text

    countries = [
        "جنوب أفريقيا", "كوريا الجنوبية", "ساحل العاج", "نيجيريا", "اليابان",
        "جورجيا", "إيطاليا", "إسبانيا", "ألمانيا", "فرنسا", "إنجلترا",
        "هولندا", "بلجيكا", "البرتغال", "البرازيل", "الأرجنتين", "المكسيك",
        "أمريكا", "مصر", "العراق", "السعودية", "الإمارات", "قطر", "الكويت",
        "البحرين", "الأردن", "المغرب", "الجزائر", "تونس", "ليبيا", "سوريا",
        "لبنان", "فلسطين", "تركيا", "الصين", "أستراليا", "الهند", "غانا",
        "السنغال", "الكاميرون", "مالي", "زامبيا", "تنزانيا", "أوغندا", "كينيا",
    ]

    found_country = False
    for country in sorted(countries, key=len, reverse=True):
        if country in prefix:
            result["country"] = country
            league = prefix.replace(country, "").strip()
            if league:
                result["league"] = league
            found_country = True
            break

    if not found_country and prefix:
        result["league"] = prefix

    return result


# =========================================================
# KOOORA MATCH PARSER
# =========================================================

def parse_kooora_match_element(match_element):
    """
    Parse ONE real Kooora match card.

    Important:
    - FIXTURE cards are ignored completely.
    - Only LIVE/RESULT cards can generate HT/FT alerts.
    - Scores are read from .fco-match-basic-data.
    - Match times elsewhere on the page are never interpreted as scores.
    """

    data_status = str(match_element.get("data-match-status", "")).upper().strip()

    # This is the most important filter. It prevents fixture times such as
    # 15:00 from being interpreted as 15-0 or similar false results.
    if data_status not in {"LIVE", "RESULT"}:
        return None

    status_el = match_element.select_one(".fco-match-status")
    status_text = clean_text(
        status_el.get_text(" ", strip=True) if status_el else ""
    )

    if data_status == "RESULT":
        status = "FT"
    elif HT_RE.search(status_text):
        status = "HT"
    else:
        # LIVE can also mean the game is currently in progress.
        # We only alert when Kooora explicitly says halftime.
        return None

    basic = match_element.select_one(".fco-match-basic-data")
    if basic is None:
        return None

    basic_text = clean_text(basic.get_text(" ", strip=True))

    # Current Kooora structure for completed/halftime games is like:
    # TEAM1 CODE 0 TEAM2 CODE 1 انتهت/استراحة
    # Therefore the first two standalone numbers in BASIC DATA are the score.
    numbers = list(SINGLE_SCORE_RE.finditer(basic_text))
    if len(numbers) < 2:
        return None

    first_score = numbers[0]
    second_score = numbers[1]

    try:
        score = (int(first_score.group(1)), int(second_score.group(1)))
    except ValueError:
        return None

    team1 = basic_text[:first_score.start()].strip()
    team2 = basic_text[first_score.end():second_score.start()].strip()

    # Kooora places a short team code after the team name, e.g. NIG / PLU.
    team1 = re.sub(r"\s+\b[A-Z]{2,5}\b\s*$", "", team1).strip()
    team2 = re.sub(r"\s+\b[A-Z]{2,5}\b\s*$", "", team2).strip()

    if not team1 or not team2 or team1 == team2:
        return None

    # Remove any accidental status text from team names.
    team1 = FT_RE.sub(" ", team1)
    team1 = HT_RE.sub(" ", team1)
    team2 = FT_RE.sub(" ", team2)
    team2 = HT_RE.sub(" ", team2)
    team1 = clean_text(team1)
    team2 = clean_text(team2)

    if not team1 or not team2:
        return None

    context = extract_competition_context(match_element)

    # Prefer the match link as a stable identity.
    link = match_element.select_one("a.fco-match-data")
    href = ""
    if link is not None:
        href = str(link.get("href", "")).strip()

    match_key = href or f"{team1}|{team2}"

    return {
        "match_key": match_key,
        "match_name": f"{team1} vs {team2}",
        "team1": team1,
        "team2": team2,
        "score": score,
        "status": status,
        "country": context["country"],
        "league": context["league"],
        "round": context["round"],
        "raw": clean_text(match_element.get_text(" ", strip=True)),
    }


# =========================================================
# FIND TODAY'S MATCHES
# =========================================================

def find_kooora_matches(soup):
    """
    Read all Kooora match cards from today's page.

    Returns two lists:
      all_today_matches = every fixture/live/result card
      alerts_matches    = only HT/FT cards ready for notification
    """

    items = soup.select(".fco-match-list-item[data-match-status]")

    all_today_matches = []
    alert_matches = []
    seen_match_keys = set()

    for item in items:
        data_status = str(item.get("data-match-status", "")).upper().strip()

        # First count/store today's cards, including future fixtures.
        basic = item.select_one(".fco-match-basic-data")
        if basic is None:
            continue

        raw_basic = clean_text(basic.get_text(" ", strip=True))

        # Only identify the card here. Do NOT parse arbitrary page numbers.
        href_el = item.select_one("a.fco-match-data")
        href = str(href_el.get("href", "")).strip() if href_el else ""
        card_key = href or raw_basic

        if card_key in seen_match_keys:
            continue
        seen_match_keys.add(card_key)

        all_today_matches.append({
            "key": card_key,
            "data_status": data_status,
            "raw": raw_basic,
        })

        parsed = parse_kooora_match_element(item)
        if parsed:
            alert_matches.append(parsed)

    return all_today_matches, alert_matches


# =========================================================
# GET KOOORA
# =========================================================

def get_kooora_page():
    urls = [KOOORA_URL, KOOORA_FALLBACK_URL]

    for url in urls:
        try:
            response = requests.get(
                url,
                headers=KOOORA_HEADERS,
                timeout=20,
                allow_redirects=True,
            )

            print(
                f"Kooora response: {response.status_code} - {url}",
                flush=True,
            )

            if response.status_code == 200:
                print(f"Kooora final URL: {response.url}", flush=True)
                print(f"Kooora HTML length: {len(response.text)}", flush=True)
                return response

        except requests.RequestException as e:
            print(f"Kooora connection error: {e}", flush=True)

    return None


# =========================================================
# SEND ALERT
# =========================================================

def format_and_send_alert(match, date_key):
    match_name = match["match_name"]
    country = match["country"]
    league = match["league"]
    status = match["status"]
    score = match["score"]
    round_name = match.get("round")

    current_time = datetime.now().strftime("%H:%M:%S")

    if status == "FT":
        title = "🚨 تنبيه: نهاية المباراة على كووورة"
        status_text = "انتهت المباراة تماماً (FT) ✅"
    else:
        title = "🟡 تنبيه: نهاية الشوط الأول على كووورة"
        status_text = "انتهى الشوط الأول (HT) ⏸️"

    print(f"Checking bookmakers for: {match_name}", flush=True)
    bookmaker_results = check_all_bookmakers()

    message = (
        f"{title}\n\n"
        f"⚽ المباراة: {match_name}\n"
        f"🔢 النتيجة: {score[0]} - {score[1]}\n"
        f"🌍 الدولة: {country}\n"
        f"🏆 البطولة: {league}"
        f"{(' — ' + round_name) if round_name else ''}\n"
        f"⏰ وقت التحديث: {current_time}\n\n"
        f"🛑 حالة كووورة:\n{status_text}\n\n"
        "📊 حالة الوصول إلى المنصات:\n"
        "(الوصول للصفحة لا يعني أن الرهان ما زال مفتوحاً)\n\n"
    )

    accessible = 0
    captcha = 0
    blocked = 0
    other = 0

    for bookmaker in TARGET_BOOKMAKERS:
        bookmaker_status = bookmaker_results.get(bookmaker, "NOT_CHECKED")
        message += (
            f"• {bookmaker}: "
            f"{bookmaker_status_icon(bookmaker_status)}\n"
        )

        if bookmaker_status == "ACCESSIBLE":
            accessible += 1
        elif bookmaker_status == "CAPTCHA":
            captcha += 1
        elif bookmaker_status == "BLOCKED":
            blocked += 1
        else:
            other += 1

    message += (
        "\n📌 الملخص:\n"
        f"🟢 صفحات يمكن الوصول إليها: {accessible}\n"
        f"🚫 CAPTCHA: {captcha}\n"
        f"🔴 محظورة: {blocked}\n"
        f"⚪ أخرى/غير متحقق: {other}\n\n"
        "ℹ️ المنصات التي يظهر فيها CAPTCHA تم استبعادها تلقائياً.\n"
        "ℹ️ لا يتم تجاوز CAPTCHA أو تسجيل الدخول أو تنفيذ أي رهان تلقائياً."
    )

    send_telegram_message(message)


# =========================================================
# PROCESS ALERTS
# =========================================================

def process_kooora_alerts(alert_matches):
    date_key = datetime.now().strftime("%Y-%m-%d")
    alerts_generated = 0

    for match in alert_matches:
        alert_key = f"{date_key}|{match['match_key']}|{match['status']}"

        if alert_key in sent_alerts:
            continue

        print(
            f"🚨 REAL MATCH DETECTED: {match['match_name']} | "
            f"{match['score'][0]}-{match['score'][1]} | {match['status']}",
            flush=True,
        )

        format_and_send_alert(match, date_key)
        sent_alerts.add(alert_key)
        alerts_generated += 1

    return alerts_generated


# =========================================================
# MAIN KOOORA CHECK
# =========================================================

def check_kooora_matches():
    response = get_kooora_page()

    if response is None:
        print("Unable to access Kooora", flush=True)
        return

    try:
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else "NO TITLE"
        print(f"Kooora title: {title[:200]}", flush=True)

        all_matches, alert_matches = find_kooora_matches(soup)

        # Today's page contains all fixtures. This number should be much larger
        # than the number of FT/HT alerts during most scans.
        print(
            f"📅 Kooora TODAY match cards found: {len(all_matches)}",
            flush=True,
        )

        fixture_count = sum(
            1 for m in all_matches if m["data_status"] == "FIXTURE"
        )
        live_count = sum(
            1 for m in all_matches if m["data_status"] == "LIVE"
        )
        result_count = sum(
            1 for m in all_matches if m["data_status"] == "RESULT"
        )

        print(
            f"   FIXTURE={fixture_count} | LIVE={live_count} | RESULT={result_count}",
            flush=True,
        )
        print(
            f"⚽ Kooora HT/FT matches ready for checking: {len(alert_matches)}",
            flush=True,
        )

        # Only parsed HT/FT cards reach this function.
        total_alerts = process_kooora_alerts(alert_matches)

        print(
            f"✅ Kooora scan finished. New alerts generated: {total_alerts}",
            flush=True,
        )

        if len(sent_alerts) > 5000:
            sent_alerts.clear()
            print("sent_alerts cleared", flush=True)

    except Exception as e:
        print(f"Error scraping Kooora: {e}", flush=True)


# =========================================================
# BOT LOOP - EVERY 60 SECONDS
# =========================================================

def bot_loop():
    print("🚀 BOT LOOP STARTED", flush=True)

    current_time = datetime.now().strftime("%H:%M:%S")
    startup_message = (
        "🚀 تم تشغيل بوت مراقبة كووورة بنجاح!\n\n"
        f"⏰ الوقت: {current_time}\n"
        "📅 مراقبة جميع مباريات اليوم في كووورة\n"
        "🟡 مراقبة HT\n"
        "🚨 مراقبة FT\n"
        "🛡️ منع نتائج/أوقات وهمية\n"
        "📊 فحص المنصات العامة عند HT/FT\n"
        "🚫 استبعاد CAPTCHA تلقائياً\n"
        "🔄 الفحص كل 60 ثانية"
    )

    print("📨 Sending Telegram startup message...", flush=True)
    send_telegram_message(startup_message)
    print("✅ Startup message finished", flush=True)

    while True:
        try:
            print("\n==============================", flush=True)
            print("🔍 Checking ALL TODAY'S Kooora matches...", flush=True)
            check_kooora_matches()
            print("✅ Kooora check finished", flush=True)
            print("⏳ Next check in 60 seconds...", flush=True)
            print("==============================\n", flush=True)
        except Exception as e:
            print(f"❌ Bot loop error: {e}", flush=True)

        time.sleep(60)


# =========================================================
# START BOT
# =========================================================

bot_thread = threading.Thread(target=bot_loop, daemon=True)
bot_thread.start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )
