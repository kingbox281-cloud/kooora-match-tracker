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
    return "Bot is running and monitoring Kooora 24/7!"


@app.route("/health")
def health():
    return "OK"


# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "YOUR_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID",
    "YOUR_CHAT_ID"
)


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("Telegram token is not configured.", flush=True)
        return None

    if not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID":
        print("Telegram chat ID is not configured.", flush=True)
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        print(
            f"Telegram: {response.status_code}",
            flush=True
        )

        return response.json()

    except Exception as e:
        print(
            f"Telegram error: {e}",
            flush=True
        )
        return None


# =========================================================
# KOOORA
# =========================================================

KOOORA_URLS = [
    "https://www.kooora.com/%D9%83%D8%B1%D8%A9-%D8%A7%D9%84%D9%82%D8%AF%D9%85/%D9%85%D8%A8%D8%A7%D8%B1%D9%8A%D8%A7%D8%AA-%D8%A7%D9%84%D9%8A%D9%88%D9%85",
    "https://www.kooora.com/default.aspx?g=matches"
]

KOOORA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en;q=0.8"
}


# =========================================================
# 18 BOOKMAKERS
# =========================================================

TARGET_BOOKMAKERS = [
    "Tipico",
    "Tipwin",
    "Merkur Bets",
    "sportwetten.de",
    "NEO.bet",
    "bet365",
    "Winamax",
    "bwin",
    "Betano",
    "Bet-at-home",
    "ODDSET",
    "Interwetten",
    "DAZN Bet",
    "AdmiralBet",
    "Betway",
    "LeoVegas",
    "VBET",
    "Bet3000"
]


# صفحات عامة فقط.
# لا يوجد تسجيل دخول ولا تجاوز CAPTCHA.

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


# =========================================================
# BOOKMAKER STATUS
# =========================================================

CAPTCHA_WORDS = [
    "captcha",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "verify that you are human",
    "are you human",
    "security check",
    "bot detection",
    "access denied",
    "cloudflare"
]


def detect_captcha(response):
    """
    يكتشف صفحات CAPTCHA / حماية البوت.
    لا يحاول تجاوزها.
    """

    text = response.text.lower()

    for word in CAPTCHA_WORDS:
        if word in text:
            return True

    server_text = (
        str(response.headers.get("server", ""))
        + " "
        + str(response.headers.get("cf-ray", ""))
        + " "
        + str(response.headers.get("cf-mitigated", ""))
    ).lower()

    for word in CAPTCHA_WORDS:
        if word in server_text:
            return True

    return False


def check_bookmaker_access(bookmaker):
    """
    يفحص فقط إمكانية الوصول إلى الصفحة العامة للمنصة.

    لا يقوم:
    - بتسجيل الدخول
    - بتجاوز CAPTCHA
    - بتنفيذ رهانات
    - بالتحايل على حماية الموقع

    النتيجة لا تعني أن السوق ما زال مفتوحاً.
    """

    url = BOOKMAKER_URLS.get(bookmaker)

    if not url:
        return "NOT_CHECKED"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=10,
            allow_redirects=True
        )

        print(
            f"{bookmaker}: HTTP {response.status_code} "
            f"{response.url}",
            flush=True
        )

        # CAPTCHA / حماية البوت
        if detect_captcha(response):
            return "CAPTCHA"

        # حالات منع الوصول
        if response.status_code in [401, 403, 429]:
            return "BLOCKED"

        if response.status_code >= 500:
            return "SERVER_ERROR"

        if response.status_code == 200:
            return "ACCESSIBLE"

        return "NOT_CHECKED"

    except requests.exceptions.Timeout:
        print(
            f"{bookmaker}: timeout",
            flush=True
        )
        return "TIMEOUT"

    except requests.exceptions.RequestException as e:
        print(
            f"{bookmaker}: {e}",
            flush=True
        )
        return "ERROR"

    except Exception as e:
        print(
            f"{bookmaker}: unexpected error: {e}",
            flush=True
        )
        return "ERROR"


def check_all_bookmakers():

    results = {}

    for bookmaker in TARGET_BOOKMAKERS:

        status = check_bookmaker_access(bookmaker)

        results[bookmaker] = status

        # إذا وجد CAPTCHA، ننتقل مباشرة للمنصة التالية
        if status == "CAPTCHA":
            print(
                f"🚫 {bookmaker}: CAPTCHA detected - skipped",
                flush=True
            )

        time.sleep(0.5)

    return results


# =========================================================
# BOOKMAKER DISPLAY
# =========================================================

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
# ALERT
# =========================================================

sent_alerts = set()


def format_and_send_alert(
    match_name,
    country,
    league,
    status_type
):

    current_time = datetime.now().strftime("%H:%M:%S")

    if status_type == "FT":

        status_text = (
            "انتهت المباراة تماماً (FT) ✅"
        )

        title = (
            "🚨 تنبيه: نهاية المباراة على كووورة"
        )

    else:

        status_text = (
            "انتهى الشوط الأول (HT) ⏸️"
        )

        title = (
            "🟡 تنبيه: نهاية الشوط الأول على كووورة"
        )

    print(
        f"Checking bookmakers for: {match_name}",
        flush=True
    )

    bookmaker_results = check_all_bookmakers()

    message = (
        f"{title}\n\n"
        f"⚽ المباراة: {match_name}\n"
        f"🌍 الدولة: {country}\n"
        f"🏆 البطولة: {league}\n"
        f"⏰ وقت التحديث: {current_time}\n\n"
        f"🛑 حالة كووورة:\n"
        f"{status_text}\n\n"
        f"📊 حالة الوصول إلى المنصات:\n"
        f"(الوصول للصفحة لا يعني أن الرهان ما زال مفتوحاً)\n\n"
    )

    accessible = 0
    captcha = 0
    blocked = 0
    other = 0

    for bookmaker in TARGET_BOOKMAKERS:

        status = bookmaker_results.get(
            bookmaker,
            "NOT_CHECKED"
        )

        icon = bookmaker_status_icon(status)

        message += (
            f"• {bookmaker}: {icon}\n"
        )

        if status == "ACCESSIBLE":
            accessible += 1

        elif status == "CAPTCHA":
            captcha += 1

        elif status == "BLOCKED":
            blocked += 1

        else:
            other += 1

    message += (
        "\n"
        "📌 الملخص:\n"
        f"🟢 صفحات يمكن الوصول إليها: {accessible}\n"
        f"🚫 CAPTCHA: {captcha}\n"
        f"🔴 محظورة: {blocked}\n"
        f"⚪ أخرى/غير متحقق: {other}\n\n"
        "ℹ️ المنصات التي يظهر فيها CAPTCHA "
        "تم استبعادها تلقائياً من الفحص.\n"
        "ℹ️ لا يتم تجاوز CAPTCHA أو تسجيل الدخول "
        "أو تنفيذ أي رهان تلقائياً."
    )

    send_telegram_message(message)


# =========================================================
# KOOORA PARSER
# =========================================================

def get_kooora_page():

    for url in KOOORA_URLS:

        try:

            response = requests.get(
                url,
                headers=KOOORA_HEADERS,
                timeout=20
            )

            print(
                f"Kooora response: "
                f"{response.status_code} - {url}",
                flush=True
            )

            if response.status_code == 200:
                return response

        except Exception as e:

            print(
                f"Kooora connection error: {e}",
                flush=True
            )

    return None


def extract_match_name(text):

    # إزالة بعض الكلمات غير المفيدة
    ignored = {
        "انتهت",
        "FT",
        "HT",
        "الشوط",
        "الأول",
        "المباراة",
        "البطولة",
        "الدوري",
        "كأس",
        "بطولة"
    }

    words = []

    for word in text.split():

        clean = word.strip()

        if len(clean) < 2:
            continue

        if clean in ignored:
            continue

        # تجاهل بعض الأرقام
        if clean.isdigit():
            continue

        words.append(clean)

    if len(words) >= 2:

        return (
            f"{words[0]} vs {words[1]}"
        )

    return "مباراة مرصودة"


def detect_status(text):

    upper_text = text.upper()

    # FT
    if (
        "انتهت" in text
        or "FT" in upper_text
    ):
        return "FT"

    # HT
    if (
        "الشوط الأول" in text
        or "HT" in upper_text
    ):
        return "HT"

    return None


def check_kooora_matches():

    response = get_kooora_page()

    if response is None:

        print(
            "❌ Unable to access Kooora",
            flush=True
        )

        return

    try:

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        current_league = "الدوري العام"
        current_country = "الدولي / محلي"

        # محاولة قراءة الصفوف
        matches = soup.find_all("tr")

        # إذا لم نجد tr، نجرب عناصر match
        if not matches:

            matches = soup.find_all(
                "div",
                class_="match"
            )

        print(
            f"Kooora elements found: {len(matches)}",
            flush=True
        )

        for match in matches:

            text = match.get_text(
                separator=" ",
                strip=True
            )

            if not text:
                continue

            # -----------------------------------------
            # البطولة
            # -----------------------------------------

            if (
                "الدوري" in text
                or "دوري" in text
                or "كأس" in text
                or "بطولة" in text
            ):

                parts = [
                    p.strip()
                    for p in text.split("-")
                    if len(p.strip()) > 3
                ]

                if parts:

                    current_league = (
                        parts[0][:60]
                    )

            # -----------------------------------------
            # الحالة
            # -----------------------------------------

            status_detected = detect_status(text)

            if not status_detected:
                continue

            # -----------------------------------------
            # اسم المباراة
            # -----------------------------------------

            match_name = extract_match_name(text)

            # -----------------------------------------
            # ID ثابت قدر الإمكان
            # -----------------------------------------

            match_id = (
                f"{match_name}|"
                f"{current_league}|"
                f"{status_detected}"
            )

            if match_id in sent_alerts:
                continue

            print(
                f"🚨 Detected: "
                f"{match_name} - "
                f"{status_detected}",
                flush=True
            )

            # إرسال التنبيه
            format_and_send_alert(
                match_name,
                current_country,
                current_league,
                status_detected
            )

            sent_alerts.add(match_id)

            # منع نمو الذاكرة بلا حدود
            if len(sent_alerts) > 1000:

                # الاحتفاظ بآخر جزء فقط
                sent_alerts.clear()

    except Exception as e:

        print(
            f"❌ Error scraping Kooora: {e}",
            flush=True
        )


# =========================================================
# BOT LOOP
# =========================================================

def bot_loop():

    print(
        "🚀 BOT LOOP STARTED",
        flush=True
    )

    current_time = datetime.now().strftime(
        "%H:%M:%S"
    )

    startup_message = (
        "🚀 تم تشغيل بوت مراقبة كووورة بنجاح!\n\n"
        f"⏰ الوقت: {current_time}\n"
        "⚽ مراقبة FT و HT\n"
        "📊 فحص المنصات العامة\n"
        "🚫 استبعاد CAPTCHA تلقائياً\n"
        "🔄 الفحص كل 60 ثانية"
    )

    print(
        "📨 Sending Telegram startup message...",
        flush=True
    )

    send_telegram_message(
        startup_message
    )

    print(
        "✅ Startup message finished",
        flush=True
    )

    while True:

        try:

            print(
                "\n==============================",
                flush=True
            )

            print(
                "🔍 Checking Kooora...",
                flush=True
            )

            check_kooora_matches()

            print(
                "✅ Kooora check finished",
                flush=True
            )

            print(
                "⏳ Next check in 60 seconds...",
                flush=True
            )

            print(
                "==============================\n",
                flush=True
            )

        except Exception as e:

            print(
                f"❌ Bot loop error: {e}",
                flush=True
            )

        time.sleep(60)


# =========================================================
# START BOT
# =========================================================

bot_thread = threading.Thread(
    target=bot_loop,
    daemon=True
)

bot_thread.start()


if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "8080"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )
