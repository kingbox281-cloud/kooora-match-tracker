import os
import time
import threading
import re
import json
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

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:

        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=15
        )

        print(
            f"Telegram: {response.status_code}",
            flush=True
        )

        try:
            return response.json()
        except Exception:
            return {
                "status_code": response.status_code
            }

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

    "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36",

    "Accept":
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,"
        "image/webp,*/*;q=0.8",

    "Accept-Language":
        "ar,en;q=0.8",

    "Cache-Control":
        "no-cache",

    "Pragma":
        "no-cache",

    "Referer":
        "https://www.kooora.com/"
}


# =========================================================
# BOOKMAKERS
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


BOOKMAKER_URLS = {

    "Tipico":
        "https://www.tipico.de/",

    "Tipwin":
        "https://www.tipwin.de/",

    "Merkur Bets":
        "https://www.merkurbets.de/",

    "sportwetten.de":
        "https://www.sportwetten.de/",

    "NEO.bet":
        "https://www.neo.bet/",

    "bet365":
        "https://www.bet365.com/",

    "Winamax":
        "https://www.winamax.de/",

    "bwin":
        "https://www.bwin.de/",

    "Betano":
        "https://www.betano.de/",

    "Bet-at-home":
        "https://www.bet-at-home.com/",

    "ODDSET":
        "https://www.oddset.de/",

    "Interwetten":
        "https://www.interwetten.com/",

    "DAZN Bet":
        "https://www.daznbet.de/",

    "AdmiralBet":
        "https://www.admiralbet.de/",

    "Betway":
        "https://betway.de/",

    "LeoVegas":
        "https://www.leovegas.com/",

    "VBET":
        "https://www.vbet.de/",

    "Bet3000":
        "https://www.bet3000.com/"
}


# =========================================================
# CAPTCHA
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

    text = response.text.lower()

    for word in CAPTCHA_WORDS:

        if word in text:
            return True

    server_text = (

        str(
            response.headers.get(
                "server",
                ""
            )
        )

        + " "

        + str(
            response.headers.get(
                "cf-ray",
                ""
            )
        )

        + " "

        + str(
            response.headers.get(
                "cf-mitigated",
                ""
            )
        )
    ).lower()

    for word in CAPTCHA_WORDS:

        if word in server_text:
            return True

    return False


# =========================================================
# BOOKMAKER ACCESS
# =========================================================

def check_bookmaker_access(bookmaker):

    url = BOOKMAKER_URLS.get(bookmaker)

    if not url:
        return "NOT_CHECKED"

    headers = {

        "User-Agent":
            KOOORA_HEADERS["User-Agent"],

        "Accept-Language":
            "de-DE,de;q=0.9,en;q=0.8"
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=10,
            allow_redirects=True
        )

        print(
            f"{bookmaker}: HTTP "
            f"{response.status_code} "
            f"{response.url}",
            flush=True
        )

        if detect_captcha(response):

            return "CAPTCHA"

        if response.status_code in [
            401,
            403,
            429
        ]:

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

        status = check_bookmaker_access(
            bookmaker
        )

        results[bookmaker] = status

        if status == "CAPTCHA":

            print(
                f"CAPTCHA: {bookmaker} - skipped",
                flush=True
            )

        time.sleep(0.5)

    return results


# =========================================================
# BOOKMAKER ICON
# =========================================================

def bookmaker_status_icon(status):

    status_icons = {

        "ACCESSIBLE":
            "🟢 يمكن الوصول للصفحة",

        "CAPTCHA":
            "🚫 CAPTCHA - تم الاستبعاد",

        "BLOCKED":
            "🔴 الوصول محظور",

        "TIMEOUT":
            "🟠 Timeout",

        "SERVER_ERROR":
            "🟠 خطأ في الخادم",

        "ERROR":
            "🔴 خطأ اتصال",

        "NOT_CHECKED":
            "⚪ لم يتم التحقق"
    }

    return status_icons.get(
        status,
        "⚪ لم يتم التحقق"
    )


# =========================================================
# ALERT MEMORY
# =========================================================

sent_alerts = set()


# =========================================================
# TEXT CLEANING
# =========================================================

def normalize_space(text):

    if not text:
        return ""

    text = text.replace(
        "\xa0",
        " "
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def clean_text(text):

    if not text:
        return ""

    text = text.replace(
        "\\u00a0",
        " "
    )

    text = text.replace(
        "\\/",
        "/"
    )

    return normalize_space(
        text
    )


# =========================================================
# FALSE POSITIVE FILTER
# =========================================================

FALSE_POSITIVE_WORDS = [

    "المباريات والنتائج",
    "المباريات",
    "النتائج",
    "view full",
    "full table",
    "view all",
    "all matches",
    "matches",
    "fixtures",
    "fixture",
    "results",
    "score",
    "ngscard",
    "viewfulltable"
]


def is_false_positive(text):

    text_lower = clean_text(
        text
    ).lower()

    for word in FALSE_POSITIVE_WORDS:

        if word.lower() in text_lower:

            return True

    return False


# =========================================================
# SCORE DETECTION
# =========================================================

def extract_score(text):

    text = clean_text(
        text
    )

    patterns = [

        r"\b(\d{1,2})\s*[:\-]\s*(\d{1,2})\b",

        r"\b(\d{1,2})\s*[–—]\s*(\d{1,2})\b"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            return (
                int(match.group(1)),
                int(match.group(2))
            )

    return None


# =========================================================
# STATUS DETECTION
# =========================================================

def detect_status(text):

    text = clean_text(
        text
    )

    # مهم:
    # FT وحدها لا تكفي.
    # يجب وجود نتيجة أيضاً.

    score = extract_score(
        text
    )

    if score is None:
        return None

    ft_patterns = [

        r"\bFT\b",

        r"\bFULL[\s_-]*TIME\b",

        r"انتهت المباراة",

        r"نهاية المباراة",

        r"نهايه المباراة"
    ]

    for pattern in ft_patterns:

        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        ):

            return "FT"

    ht_patterns = [

        r"\bHT\b",

        r"\bHALF[\s_-]*TIME\b",

        r"نهاية الشوط",

        r"نهايه الشوط",

        r"الشوط الأول",

        r"الشوط الاول",

        r"بين الشوطين"
    ]

    for pattern in ht_patterns:

        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        ):

            return "HT"

    return None


# =========================================================
# EXTRACT TEAM NAMES
# =========================================================

def extract_team_names(text):

    text = clean_text(
        text
    )

    if not text:
        return None

    if is_false_positive(text):

        return None

    score = extract_score(
        text
    )

    if score is None:

        return None

    # حذف FT / HT
    cleaned = re.sub(
        r"\bFT\b|\bHT\b",
        " ",
        text,
        flags=re.IGNORECASE
    )

    cleaned = re.sub(
        r"\bFULL[\s_-]*TIME\b|"
        r"\bHALF[\s_-]*TIME\b",
        " ",
        cleaned,
        flags=re.IGNORECASE
    )

    # حذف عبارات الحالة
    cleaned = re.sub(
        r"انتهت المباراة|"
        r"نهاية المباراة|"
        r"نهايه المباراة|"
        r"نهاية الشوط|"
        r"نهايه الشوط|"
        r"الشوط الأول|"
        r"الشوط الاول",
        " ",
        cleaned,
        flags=re.IGNORECASE
    )

    # حذف النتيجة
    cleaned = re.sub(
        r"\b\d{1,2}\s*[:\-–—]\s*\d{1,2}\b",
        " ",
        cleaned
    )

    cleaned = normalize_space(
        cleaned
    )

    separators = [

        r"\s+[-–—]\s+",

        r"\s+vs\.?\s+",

        r"\s+v\s+",

        r"\s+×\s+",

        r"\s+/\s+"
    ]

    for separator in separators:

        parts = re.split(
            separator,
            cleaned,
            maxsplit=1,
            flags=re.IGNORECASE
        )

        if len(parts) == 2:

            team1 = normalize_space(
                parts[0]
            )

            team2 = normalize_space(
                parts[1]
            )

            if (
                len(team1) >= 2
                and len(team2) >= 2
                and len(team1) <= 100
                and len(team2) <= 100
            ):

                if not is_false_positive(
                    team1
                ) and not is_false_positive(
                    team2
                ):

                    return (
                        team1,
                        team2
                    )

    return None


# =========================================================
# MATCH NAME
# =========================================================

def extract_match_name(text):

    teams = extract_team_names(
        text
    )

    if not teams:

        return None

    team1, team2 = teams

    return (
        f"{team1} vs {team2}"
    )


# =========================================================
# LEAGUE
# =========================================================

def extract_league(
    text,
    default="الدوري العام"
):

    text = clean_text(
        text
    )

    patterns = [

        r"(?:البطولة|الدوري)\s*[:\-]\s*([^|]{3,80})",

        r"(الدوري[^|]{2,80})",

        r"(كأس[^|]{2,80})",

        r"(بطولة[^|]{2,80})"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            value = normalize_space(
                match.group(1)
            )

            value = value.strip(
                " -|,"
            )

            if len(value) >= 3:

                return value[:80]

    return default


# =========================================================
# VALID MATCH
# =========================================================

def is_real_match(text):

    text = clean_text(
        text
    )

    if not text:
        return False

    if is_false_positive(
        text
    ):

        return False

    score = extract_score(
        text
    )

    if score is None:
        return False

    status = detect_status(
        text
    )

    if status not in [
        "FT",
        "HT"
    ]:

        return False

    teams = extract_team_names(
        text
    )

    if not teams:
        return False

    team1, team2 = teams

    # منع الكلمات العامة
    bad_team_words = [

        "المباريات",
        "النتائج",
        "الدوري",
        "البطولة",
        "الجولة",
        "view",
        "full",
        "table",
        "ngscard"
    ]

    team1_lower = team1.lower()
    team2_lower = team2.lower()

    for word in bad_team_words:

        if (
            word.lower() in team1_lower
            or word.lower() in team2_lower
        ):

            return False

    return True


# =========================================================
# DOM CANDIDATES
# =========================================================

def find_dom_match_candidates(
    soup
):

    candidates = []

    # -----------------------------------------------------
    # TABLE ROWS
    # -----------------------------------------------------

    for element in soup.find_all(
        "tr"
    ):

        text = clean_text(
            element.get_text(
                " ",
                strip=True
            )
        )

        if is_real_match(
            text
        ):

            candidates.append(
                element
            )

    # -----------------------------------------------------
    # DIV / LI / ARTICLE
    # -----------------------------------------------------

    keywords = [

        "match",
        "matches",
        "game",
        "games",
        "fixture",
        "fixtures",
        "event",
        "events",
        "score",
        "result"
    ]

    for element in soup.find_all(
        [
            "div",
            "li",
            "article",
            "section"
        ]
    ):

        classes = " ".join(
            element.get(
                "class",
                []
            )
        )

        element_id = str(
            element.get(
                "id",
                ""
            )
        )

        haystack = (
            f"{classes} {element_id}"
        ).lower()

        if not any(
            keyword in haystack
            for keyword in keywords
        ):

            continue

        text = clean_text(
            element.get_text(
                " ",
                strip=True
            )
        )

        if is_real_match(
            text
        ):

            candidates.append(
                element
            )

    # -----------------------------------------------------
    # REMOVE DUPLICATES
    # -----------------------------------------------------

    unique = []

    seen = set()

    for element in candidates:

        text = clean_text(
            element.get_text(
                " ",
                strip=True
            )
        )

        key = text[:500]

        if key in seen:
            continue

        seen.add(
            key
        )

        unique.append(
            element
        )

    return unique


# =========================================================
# SCRIPT JSON
# =========================================================

def walk_json_for_match_strings(
    value,
    results
):

    if isinstance(
        value,
        dict
    ):

        for key, child in value.items():

            if isinstance(
                child,
                str
            ):

                text = clean_text(
                    child
                )

                if is_real_match(
                    text
                ):

                    results.append(
                        text
                    )

            else:

                walk_json_for_match_strings(
                    child,
                    results
                )

    elif isinstance(
        value,
        list
    ):

        for child in value:

            walk_json_for_match_strings(
                child,
                results
            )


def extract_script_candidates(
    soup
):

    candidates = []

    for script in soup.find_all(
        "script"
    ):

        raw = (
            script.string
            or script.get_text()
        )

        if not raw:
            continue

        raw = raw.strip()

        if len(raw) < 10:
            continue

        script_type = str(
            script.get(
                "type",
                ""
            )
        ).lower()

        # -------------------------------------------------
        # JSON
        # -------------------------------------------------

        if "json" in script_type:

            try:

                data = json.loads(
                    raw
                )

                found = []

                walk_json_for_match_strings(
                    data,
                    found
                )

                candidates.extend(
                    found
                )

            except Exception:
                pass

        # -------------------------------------------------
        # JAVASCRIPT
        # -------------------------------------------------

        if re.search(
            r"\b(?:FT|HT)\b|"
            r"انتهت المباراة|"
            r"نهاية المباراة|"
            r"نهاية الشوط",
            raw,
            flags=re.IGNORECASE
        ):

            # نبحث عن نتيجة أولاً
            score_matches = list(
                re.finditer(
                    r"\b\d{1,2}\s*[:\-–—]\s*\d{1,2}\b",
                    raw
                )
            )

            for score_match in score_matches:

                start = max(
                    0,
                    score_match.start() - 350
                )

                end = min(
                    len(raw),
                    score_match.end() + 350
                )

                fragment = clean_text(
                    raw[start:end]
                )

                if is_real_match(
                    fragment
                ):

                    candidates.append(
                        fragment
                    )

    return candidates


# =========================================================
# RAW TEXT
# =========================================================

def extract_raw_text_candidates(
    soup
):

    page_text = clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    )

    candidates = []

    # يجب وجود نتيجة + FT/HT
    score_pattern = (
        r"\b\d{1,2}\s*[:\-–—]\s*\d{1,2}\b"
    )

    for score_match in re.finditer(
        score_pattern,
        page_text
    ):

        start = max(
            0,
            score_match.start() - 180
        )

        end = min(
            len(page_text),
            score_match.end() + 180
        )

        fragment = page_text[
            start:end
        ]

        if is_real_match(
            fragment
        ):

            candidates.append(
                fragment
            )

    return candidates


# =========================================================
# GET KOOORA
# =========================================================

def get_kooora_page():

    for url in KOOORA_URLS:

        try:

            response = requests.get(
                url,
                headers=KOOORA_HEADERS,
                timeout=20,
                allow_redirects=True
            )

            print(
                f"Kooora response: "
                f"{response.status_code} - {url}",
                flush=True
            )

            if response.status_code == 200:

                print(
                    f"Kooora final URL: "
                    f"{response.url}",
                    flush=True
                )

                print(
                    f"Kooora HTML length: "
                    f"{len(response.text)}",
                    flush=True
                )

                return response

        except Exception as e:

            print(
                f"Kooora connection error: {e}",
                flush=True
            )

    return None


# =========================================================
# SEND MATCH ALERT
# =========================================================

def format_and_send_alert(
    match_name,
    country,
    league,
    status_type,
    score
):

    current_time = datetime.now().strftime(
        "%H:%M:%S"
    )

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
        f"Checking bookmakers for: "
        f"{match_name}",
        flush=True
    )

    bookmaker_results = (
        check_all_bookmakers()
    )

    message = (

        f"{title}\n\n"

        f"⚽ المباراة: {match_name}\n"

        f"🔢 النتيجة: "
        f"{score[0]} - {score[1]}\n"

        f"🌍 الدولة: {country}\n"

        f"🏆 البطولة: {league}\n"

        f"⏰ وقت التحديث: "
        f"{current_time}\n\n"

        f"🛑 حالة كووورة:\n"
        f"{status_text}\n\n"

        "📊 حالة الوصول إلى المنصات:\n"
        "(الوصول للصفحة لا يعني أن "
        "الرهان ما زال مفتوحاً)\n\n"
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

        message += (
            f"• {bookmaker}: "
            f"{bookmaker_status_icon(status)}\n"
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

        "\n📌 الملخص:\n"

        f"🟢 صفحات يمكن الوصول إليها: "
        f"{accessible}\n"

        f"🚫 CAPTCHA: "
        f"{captcha}\n"

        f"🔴 محظورة: "
        f"{blocked}\n"

        f"⚪ أخرى/غير متحقق: "
        f"{other}\n\n"

        "ℹ️ المنصات التي يظهر فيها "
        "CAPTCHA تم استبعادها تلقائياً.\n"

        "ℹ️ لا يتم تجاوز CAPTCHA أو "
        "تسجيل الدخول أو تنفيذ أي رهان تلقائياً."
    )

    send_telegram_message(
        message
    )


# =========================================================
# PROCESS CANDIDATE
# =========================================================

def process_candidate_text(
    text,
    country,
    league,
    seen_candidates
):

    text = clean_text(
        text
    )

    if not is_real_match(
        text
    ):

        return 0

    status = detect_status(
        text
    )

    if status not in [
        "FT",
        "HT"
    ]:

        return 0

    match_name = extract_match_name(
        text
    )

    if not match_name:

        return 0

    score = extract_score(
        text
    )

    if score is None:

        return 0

    league = extract_league(
        text,
        league
    )

    # المفتاح لمنع التكرار
    match_id = (

        f"{match_name}|"
        f"{score[0]}-{score[1]}|"
        f"{status}"
    )

    if match_id in seen_candidates:

        return 0

    if match_id in sent_alerts:

        return 0

    seen_candidates.add(
        match_id
    )

    print(
        f"🚨 REAL MATCH DETECTED: "
        f"{match_name} | "
        f"{score[0]}-{score[1]} | "
        f"{status}",
        flush=True
    )

    format_and_send_alert(
        match_name,
        country,
        league,
        status,
        score
    )

    sent_alerts.add(
        match_id
    )

    return 1


# =========================================================
# MAIN KOOORA CHECK
# =========================================================

def check_kooora_matches():

    response = get_kooora_page()

    if response is None:

        print(
            "Unable to access Kooora",
            flush=True
        )

        return

    try:

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        if soup.title:

            title = soup.title.get_text(
                " ",
                strip=True
            )

        else:

            title = "NO TITLE"

        print(
            f"Kooora title: "
            f"{title[:200]}",
            flush=True
        )

        country = (
            "الدولي / محلي"
        )

        league = (
            "الدوري العام"
        )

        seen_candidates = set()

        total_alerts = 0

        # =================================================
        # DOM
        # =================================================

        dom_candidates = (
            find_dom_match_candidates(
                soup
            )
        )

        print(
            f"Kooora REAL DOM candidates: "
            f"{len(dom_candidates)}",
            flush=True
        )

        for element in dom_candidates:

            text = element.get_text(
                " ",
                strip=True
            )

            total_alerts += (
                process_candidate_text(
                    text,
                    country,
                    league,
                    seen_candidates
                )
            )

        # =================================================
        # SCRIPTS
        # =================================================

        script_candidates = (
            extract_script_candidates(
                soup
            )
        )

        print(
            f"Kooora REAL script candidates: "
            f"{len(script_candidates)}",
            flush=True
        )

        for text in script_candidates:

            total_alerts += (
                process_candidate_text(
                    text,
                    country,
                    league,
                    seen_candidates
                )
            )

        # =================================================
        # RAW TEXT FALLBACK
        # =================================================

        if (
            len(dom_candidates) == 0
            and len(script_candidates) == 0
        ):

            raw_candidates = (
                extract_raw_text_candidates(
                    soup
                )
            )

            print(
                f"Kooora REAL raw candidates: "
                f"{len(raw_candidates)}",
                flush=True
            )

            for text in raw_candidates:

                total_alerts += (
                    process_candidate_text(
                        text,
                        country,
                        league,
                        seen_candidates
                    )
                )

        # =================================================
        # DEBUG
        # =================================================

        print(
            f"Kooora scan finished. "
            f"REAL alerts generated: "
            f"{total_alerts}",
            flush=True
        )

        # منع زيادة الذاكرة
        if len(sent_alerts) > 1000:

            sent_alerts.clear()

            print(
                "sent_alerts cleared",
                flush=True
            )

    except Exception as e:

        print(
            f"Error scraping Kooora: {e}",
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

        "🛡️ منع التنبيهات الوهمية\n"

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

        time.sleep(
            60
        )


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
