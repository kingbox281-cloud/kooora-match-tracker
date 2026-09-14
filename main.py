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
            timeout=15
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
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ar,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://www.kooora.com/"
}

# =========================================================
# BOOKMAKERS
# =========================================================

TARGET_BOOKMAKERS = [
    "Tipico", "Tipwin", "Merkur Bets", "sportwetten.de", "NEO.bet",
    "bet365", "Winamax", "bwin", "Betano", "Bet-at-home", "ODDSET",
    "Interwetten", "DAZN Bet", "AdmiralBet", "Betway", "LeoVegas",
    "VBET", "Bet3000"
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

# =========================================================
# CAPTCHA
# =========================================================

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

    server_text = (
        str(response.headers.get("server", "")) + " " +
        str(response.headers.get("cf-ray", "")) + " " +
        str(response.headers.get("cf-mitigated", ""))
    ).lower()

    return any(word in server_text for word in CAPTCHA_WORDS)

# =========================================================
# BOOKMAKER ACCESS
# =========================================================

def check_bookmaker_access(bookmaker):
    url = BOOKMAKER_URLS.get(bookmaker)

    if not url:
        return "NOT_CHECKED"

    headers = {
        "User-Agent": KOOORA_HEADERS["User-Agent"],
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"
    }

    try:
        response = requests.get(
            url, headers=headers, timeout=10, allow_redirects=True
        )

        print(
            f"{bookmaker}: HTTP {response.status_code} {response.url}",
            flush=True
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
    status_icons = {
        "ACCESSIBLE": "🟢 يمكن الوصول للصفحة",
        "CAPTCHA": "🚫 CAPTCHA - تم الاستبعاد",
        "BLOCKED": "🔴 الوصول محظور",
        "TIMEOUT": "🟠 Timeout",
        "SERVER_ERROR": "🟠 خطأ في الخادم",
        "ERROR": "🔴 خطأ اتصال",
        "NOT_CHECKED": "⚪ لم يتم التحقق"
    }
    return status_icons.get(status, "⚪ لم يتم التحقق")

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

    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def clean_text(text):
    if not text:
        return ""

    text = str(text)
    text = text.replace("\\u00a0", " ")
    text = text.replace("\\/", "/")

    # تحويل الأرقام العربية والفارسية إلى أرقام إنجليزية.
    translation = str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789"
    )
    text = text.translate(translation)

    return normalize_space(text)

# =========================================================
# METADATA
# =========================================================

def get_element_metadata(element):
    values = []

    wanted = [
        "class", "id", "title", "aria-label",
        "data-status", "data-state", "data-result",
        "data-match-status", "data-game-status",
        "data-event-status", "data-testid"
    ]

    for attr in wanted:
        if element.has_attr(attr):
            value = element.get(attr)

            if isinstance(value, list):
                value = " ".join(str(x) for x in value)

            values.append(f"{attr}={value}")

    return clean_text(" ".join(values))

# =========================================================
# FALSE POSITIVE FILTER
# =========================================================

FALSE_POSITIVE_WORDS = [
    "المباريات والنتائج", "المباريات", "النتائج",
    "view full", "full table", "view all", "all matches",
    "matches", "fixtures", "fixture", "results", "score",
    "ngscard", "viewfulltable"
]

def is_false_positive(text):
    text_lower = clean_text(text).lower()

    return any(
        word.lower() in text_lower
        for word in FALSE_POSITIVE_WORDS
    )

# =========================================================
# SCORE / STATUS / TEAM DETECTION
# =========================================================

# Kooora current DOM uses separate elements for teams, score and status.
# Examples seen in the live HTML:
#   fco-match-list-item[data-match-status="RESULT"]
#   fco-match-data
#   fco-match-basic-data
#   fco-match-status

SCORE_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*[:\-–—]\s*(\d{1,2})(?!\d)"
)

SINGLE_SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")

FT_PATTERNS = [
    r"\bFT\b", r"\bFULL[\s_-]*TIME\b",
    r"انتهت(?:\s+المباراة)?", r"إنتهت(?:\s+المباراة)?",
    r"النهاية", r"نهاية\s+المباراة", r"نهايه\s+المباراة"
]

HT_PATTERNS = [
    r"\bHT\b", r"\bHALF[\s_-]*TIME\b",
    r"استراحة", r"الشوط\s+الأول", r"الشوط\s+الاول",
    r"نهاية\s+الشوط", r"نهايه\s+الشوط", r"بين\s+الشوطين"
]

STATUS_RE = re.compile(
    r"انتهت|إنتهت|النهاية|نهاية المباراة|استراحة|نهاية الشوط|"
    r"الشوط الأول|الشوط الاول|بين الشوطين|\bFT\b|\bHT\b|"
    r"FULL[\s_-]*TIME|HALF[\s_-]*TIME",
    re.IGNORECASE
)


def extract_score(text):
    text = clean_text(text)
    match = SCORE_RE.search(text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def detect_status(text):
    text = clean_text(text)
    for pattern in FT_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return "FT"
    for pattern in HT_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return "HT"
    return None


def _class_text(element):
    return " ".join(str(x) for x in element.get("class", []))


def _looks_like_team_element(element):
    hay = (_class_text(element) + " " + str(element.get("data-testid", ""))).lower()
    return any(x in hay for x in ["team", "competitor", "participant"])


def _looks_like_score_element(element):
    hay = (_class_text(element) + " " + str(element.get("data-testid", ""))).lower()
    return any(x in hay for x in ["score", "result", "goals"])


def _clean_team_value(value):
    value = clean_text(value)
    if not value:
        return ""
    value = STATUS_RE.sub(" ", value)
    value = normalize_space(value)
    return value.strip("-–—|:")


def _extract_score_values_from_match(match_element):
    """Get two numeric scores from the match DOM, preferring score elements."""
    values = []

    # First: elements whose class/id explicitly suggests score/result.
    for el in match_element.find_all(True):
        hay = (
            _class_text(el) + " " + str(el.get("id", "")) + " " +
            str(el.get("data-testid", ""))
        ).lower()
        if not any(x in hay for x in ["score", "result", "goals"]):
            continue
        text = clean_text(el.get_text(" ", strip=True))
        m = SCORE_RE.search(text)
        if m:
            return int(m.group(1)), int(m.group(2))
        nums = SINGLE_SCORE_RE.findall(text)
        if nums:
            for n in nums:
                values.append(int(n))
                if len(values) == 2:
                    return values[0], values[1]

    # Second: inspect the basic-data block and its small descendants.
    basic = match_element.select_one(".fco-match-basic-data")
    roots = [basic] if basic else []
    roots.append(match_element)

    for root in roots:
        for el in root.find_all(["span", "div", "strong", "b", "em", "p"]):
            text = clean_text(el.get_text(" ", strip=True))
            if not text or len(text) > 40:
                continue
            m = SCORE_RE.fullmatch(text)
            if m:
                return int(m.group(1)), int(m.group(2))
            if SINGLE_SCORE_RE.fullmatch(text):
                values.append(int(text))
                if len(values) >= 2:
                    return values[-2], values[-1]

    # Last fallback: colon/dash notation anywhere in the match.
    text = clean_text(match_element.get_text(" ", strip=True))
    return extract_score(text)


def _extract_team_values_from_match(match_element):
    """Extract the two team names from Kooora's match card."""
    basic = match_element.select_one(".fco-match-basic-data")
    if basic is None:
        basic = match_element.select_one(".fco-match-data") or match_element

    full = clean_text(basic.get_text(" ", strip=True))
    full = re.sub(r"\s+", " ", full).strip()

    # Remove the final status.
    full = re.sub(
        r"\s+(?:انتهت|إنتهت|استراحة|نهاية الشوط|نهاية المباراة|FT|HT)\b.*$",
        "", full, flags=re.I
    ).strip()

    # Current Kooora text is normally:
    # TEAM1 CODE SCORE TEAM2 CODE SCORE
    scores = list(re.finditer(r"(?<!\d)(\d{1,2})(?!\d)", full))
    if len(scores) >= 2:
        a, b = scores[0], scores[1]
        left = full[:a.start()].strip()
        right = full[a.end():b.start()].strip()

        # Remove the Kooora 2-4 letter team code.
        left = re.sub(r"\s+\b[A-Z]{2,4}\b\s*$", "", left).strip()
        right = re.sub(r"\s+\b[A-Z]{2,4}\b\s*$", "", right).strip()

        if left and right and left != right:
            return [_clean_team_value(left), _clean_team_value(right)]

    # Fallback: inspect likely team elements, but never accept the same
    # element/text twice.
    result = []
    for el in basic.find_all(["span", "div", "a", "p", "strong"]):
        classes = " ".join(el.get("class", []))
        if "fco-match-status" in classes:
            continue
        text = clean_text(el.get_text(" ", strip=True))
        value = _clean_team_value(text)
        if not value or re.fullmatch(r"[A-Z]{2,4}", value):
            continue
        if _looks_like_score_element(el):
            continue
        if value not in result:
            result.append(value)

    return result[:2]


def _extract_kooora_competition_context(match_element):
    """
    Read competition/country/round from the Kooora section containing the
    match. Example section text:
    الدوري النيجيري للمحترفين نيجيريا الجولة 3 نيجر تورنادوس NIG 1 ...
    """
    result = {"country": None, "league": None, "round": None}

    section = None
    parent = match_element.parent

    for _ in range(8):
        if parent is None:
            break
        classes = " ".join(parent.get("class", []))
        if "match-list_livescores-match-list__section" in classes:
            section = parent
            break
        parent = parent.parent

    if section is None:
        return result

    # The section header is represented by an element containing "الجولة".
    # Its text is much safer than parsing the complete section container.
    header = None
    for el in section.find_all(["div", "span", "h1", "h2", "h3", "h4"]):
        text = clean_text(el.get_text(" ", strip=True))
        if "الجولة" in text:
            # Prefer the smallest element that still contains the header.
            if header is None or len(text) < len(header[0]):
                header = (text, el)

    header_text = header[0] if header else ""

    round_match = re.search(r"الجولة\s*[:\-]?\s*(\d+)", header_text, re.I)
    if round_match:
        result["round"] = f"الجولة {round_match.group(1)}"

    # Remove the round and everything after it. In the observed Kooora DOM,
    # what remains is competition + country.
    prefix = re.sub(
        r"\s*الجولة\s*[:\-]?\s*\d+.*$",
        "",
        header_text,
        flags=re.I,
    ).strip()

    # Known country names. Match the longest first for names such as
    # "جنوب أفريقيا" and "كوريا الجنوبية".
    countries = [
        "جنوب أفريقيا", "كوريا الجنوبية", "ساحل العاج",
        "نيجيريا", "اليابان", "جورجيا", "إيطاليا", "إسبانيا",
        "ألمانيا", "فرنسا", "إنجلترا", "هولندا", "بلجيكا",
        "البرتغال", "البرازيل", "الأرجنتين", "المكسيك", "أمريكا",
        "مصر", "العراق", "السعودية", "الإمارات", "قطر", "الكويت",
        "البحرين", "الأردن", "المغرب", "الجزائر", "تونس", "ليبيا",
        "سوريا", "لبنان", "فلسطين", "تركيا", "الصين", "أستراليا",
        "الهند", "غانا", "السنغال", "الكاميرون", "مالي", "زامبيا",
        "تنزانيا", "أوغندا", "كينيا",
    ]

    for country in sorted(countries, key=len, reverse=True):
        if country in prefix:
            result["country"] = country
            result["league"] = prefix.replace(country, "").strip()
            break

    if result["league"] is None and prefix:
        result["league"] = prefix

    return result


def parse_kooora_match_element(match_element):
    """Parse one fco-match-list-item without requiring all fields in one text node."""
    status_el = match_element.select_one(".fco-match-status")
    status_text = clean_text(status_el.get_text(" ", strip=True)) if status_el else clean_text(match_element.get_text(" ", strip=True))
    status = detect_status(status_text)

    if status not in ["FT", "HT"]:
        # data-match-status=RESULT strongly indicates FT/result.
        if str(match_element.get("data-match-status", "")).upper() == "RESULT":
            whole = clean_text(match_element.get_text(" ", strip=True))
            if re.search(r"انتهت|إنتهت|\bFT\b|FULL[\s_-]*TIME", whole, re.I):
                status = "FT"

    if status not in ["FT", "HT"]:
        return None

    score = _extract_score_values_from_match(match_element)

    # IMPORTANT: On the current Kooora DOM the same team text can be repeated
    # by nested elements. The reliable representation is the basic-data line:
    #   TEAM CODE SCORE TEAM CODE SCORE انتهت
    # Parse the two sides directly from the score positions first.
    basic = match_element.select_one(".fco-match-basic-data")
    basic_text = (
        clean_text(basic.get_text(" ", strip=True))
        if basic
        else clean_text(match_element.get_text(" ", strip=True))
    )

    teams = None
    nums = list(SINGLE_SCORE_RE.finditer(basic_text))

    if score and len(nums) >= 2:
        # Find the first two numeric tokens matching the actual final score.
        wanted = [str(score[0]), str(score[1])]
        positions = []
        wanted_index = 0

        for m in nums:
            if wanted_index < 2 and m.group(0) == wanted[wanted_index]:
                positions.append(m)
                wanted_index += 1

        if len(positions) == 2:
            first_score = positions[0]
            second_score = positions[1]

            left = basic_text[:first_score.start()].strip()
            middle = basic_text[first_score.end():second_score.start()].strip()

            # Kooora appends a 2-4 letter Latin team abbreviation to each name.
            # The second team's code is at the END of the middle slice.
            left = re.sub(r"\s+\b[A-Z]{2,4}\b\s*$", "", left).strip()
            middle = re.sub(r"^\b[A-Z]{2,4}\b\s+", "", middle).strip()
            middle = re.sub(r"\s+\b[A-Z]{2,4}\b\s*$", "", middle).strip()

            # Remove any remaining status token if it leaked into the slice.
            left = _clean_team_value(left)
            middle = _clean_team_value(middle)

            if left and middle:
                teams = (left, middle)

    # DOM team elements are only a fallback because they may repeat the same
    # team at multiple nesting levels.
    if not teams:
        teams = _extract_team_values_from_match(match_element)

    if not teams:
        return None

    match_name = f"{teams[0]} vs {teams[1]}"
    if score is None:
        return None

    context = _extract_kooora_competition_context(match_element)

    return {
        "match_name": match_name,
        "team1": teams[0],
        "team2": teams[1],
        "score": score,
        "status": status,
        "country": context.get("country"),
        "league": context.get("league"),
        "round": context.get("round"),
        "raw": clean_text(match_element.get_text(" ", strip=True))
    }

# =========================================================
# LEAGUE
# =========================================================

def extract_league(text, default="الدوري العام"):
    text = clean_text(text)

    patterns = [
        r"(?:البطولة|الدوري)\s*[:\-]\s*([^|]{3,80})",
        r"(الدوري[^|]{2,80})",
        r"(كأس[^|]{2,80})",
        r"(بطولة[^|]{2,80})"
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            value = normalize_space(match.group(1)).strip(" -|,")

            if len(value) >= 3:
                return value[:80]

    return default

# =========================================================
# VALID MATCH
# =========================================================

def is_real_match(text):
    text = clean_text(text)

    if not text or is_false_positive(text):
        return False

    if extract_score(text) is None:
        return False

    status = detect_status(text)

    if status not in ["FT", "HT"]:
        return False

    teams = extract_team_names(text)

    if not teams:
        return False

    bad_team_words = [
        "المباريات", "النتائج", "الدوري", "البطولة",
        "الجولة", "view", "full", "table", "ngscard"
    ]

    for team in teams:
        team_lower = team.lower()

        if any(word.lower() in team_lower for word in bad_team_words):
            return False

    return True

# =========================================================
# DEBUG: FIND REAL HTML STRUCTURE
# =========================================================

def debug_kooora_structure(soup, max_scores=20):
    """
    هذا الجزء مؤقت للتشخيص.
    لا يشترط وجود FT/HT في نفس العنصر الذي يحتوي النتيجة.
    يطبع عناصر النتائج + آباءها حتى نعرف بنية كووورة الحقيقية.
    """

    print("\n" + "=" * 70, flush=True)
    print("🔬 KOOORA HTML STRUCTURE DEBUG", flush=True)
    print("=" * 70, flush=True)

    score_elements = []
    seen = set()

    # البحث عن كل عنصر صغير يحتوي نتيجة.
    for element in soup.find_all(
        ["span", "div", "li", "a", "td", "strong", "b"]
    ):
        text = clean_text(element.get_text(" ", strip=True))

        if not text or len(text) > 180:
            continue

        score = extract_score(text)

        if score is None:
            continue

        key = (
            element.name,
            text,
            get_element_metadata(element)
        )

        if key in seen:
            continue

        seen.add(key)
        score_elements.append(element)

        if len(score_elements) >= max_scores:
            break

    print(
        f"🔢 Elements containing scores found: {len(score_elements)}",
        flush=True
    )

    # طباعة العنصر ثم حتى 3 آباء.
    for index, element in enumerate(score_elements, 1):
        text = clean_text(element.get_text(" ", strip=True))
        score = extract_score(text)
        metadata = get_element_metadata(element)

        print(f"\n[RESULT {index}]")
        print(f"TAG: {element.name}")
        print(f"TEXT: {text[:180]}")
        print(f"SCORE: {score}")
        print(f"ATTR: {metadata[:700]}")

        parent = element.parent

        for level in range(1, 4):
            if not parent or not getattr(parent, "name", None):
                break

            parent_text = clean_text(
                parent.get_text(" ", strip=True)
            )

            if len(parent_text) > 1000:
                parent_text = parent_text[:1000] + "..."

            parent_meta = get_element_metadata(parent)

            print(
                f"PARENT {level}: "
                f"<{parent.name}> "
                f"TEXT={parent_text[:1000]}"
            )

            if parent_meta:
                print(f"PARENT {level} ATTR: {parent_meta[:700]}")

            parent = parent.parent

    # بحث مستقل عن حالات المباراة.
    print("\n--- STATUS TOKENS FOUND ---", flush=True)

    status_regex = re.compile(
        r"انتهت|إنتهت|النهاية|نهاية المباراة|استراحة|"
        r"نهاية الشوط|الشوط الأول|الشوط الاول|\bFT\b|\bHT\b|"
        r"FULL[\s_-]*TIME|HALF[\s_-]*TIME",
        re.IGNORECASE
    )

    statuses = []
    status_seen = set()

    for element in soup.find_all(
        ["span", "div", "li", "a", "td", "strong", "b"]
    ):
        text = clean_text(element.get_text(" ", strip=True))

        if not text or len(text) > 250:
            continue

        match = status_regex.search(text)

        if not match:
            continue

        key = (element.name, text, get_element_metadata(element))

        if key in status_seen:
            continue

        status_seen.add(key)
        statuses.append(element)

        if len(statuses) >= 20:
            break

    print(
        f"🟡 Status elements found: {len(statuses)}",
        flush=True
    )

    for index, element in enumerate(statuses, 1):
        print(f"\n[STATUS {index}]")
        print(f"TAG: {element.name}")
        print(
            "TEXT:",
            clean_text(element.get_text(" ", strip=True))[:300]
        )
        print(
            "ATTR:",
            get_element_metadata(element)[:700]
        )

    print("=" * 70, flush=True)
    print("🔬 KOOORA HTML STRUCTURE DEBUG END", flush=True)
    print("=" * 70 + "\n", flush=True)

# =========================================================
# DOM CANDIDATES
# =========================================================

def find_dom_match_candidates(soup):
    candidates = []
    seen = set()

    # Current Kooora structure.
    items = soup.select('.fco-match-list-item[data-match-status]')
    if not items:
        items = soup.select('.fco-match-list-item')

    for item in items:
        parsed = parse_kooora_match_element(item)
        if not parsed:
            continue

        key = (
            parsed["match_name"],
            parsed["score"],
            parsed["status"]
        )
        if key in seen:
            continue
        seen.add(key)
        candidates.append(parsed)

    print(f"Kooora current DOM match items: {len(items)}", flush=True)
    return candidates

# =========================================================
# SCRIPT JSON
# =========================================================

def walk_json_for_match_strings(value, results):
    if isinstance(value, dict):
        for child in value.values():
            if isinstance(child, str):
                text = clean_text(child)

                if is_real_match(text):
                    results.append(text)
            else:
                walk_json_for_match_strings(child, results)

    elif isinstance(value, list):
        for child in value:
            walk_json_for_match_strings(child, results)

def extract_script_candidates(soup):
    candidates = []

    for script in soup.find_all("script"):
        raw = script.string or script.get_text()

        if not raw:
            continue

        raw = raw.strip()

        if len(raw) < 10:
            continue

        script_type = str(script.get("type", "")).lower()

        if "json" in script_type:
            try:
                data = json.loads(raw)
                found = []
                walk_json_for_match_strings(data, found)
                candidates.extend(found)
            except Exception:
                pass

        if re.search(
            r"\b(?:FT|HT)\b|انتهت|نهاية المباراة|نهاية الشوط|استراحة",
            raw,
            flags=re.IGNORECASE
        ):
            for score_match in SCORE_RE.finditer(raw):
                start = max(0, score_match.start() - 350)
                end = min(len(raw), score_match.end() + 350)

                fragment = clean_text(raw[start:end])

                if is_real_match(fragment):
                    candidates.append(fragment)

    return candidates

# =========================================================
# RAW TEXT
# =========================================================

def extract_raw_text_candidates(soup):
    page_text = clean_text(soup.get_text(" ", strip=True))
    candidates = []

    for score_match in SCORE_RE.finditer(page_text):
        start = max(0, score_match.start() - 180)
        end = min(len(page_text), score_match.end() + 180)

        fragment = page_text[start:end]

        if is_real_match(fragment):
            candidates.append(fragment)

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
                f"Kooora response: {response.status_code} - {url}",
                flush=True
            )

            if response.status_code == 200:
                print(
                    f"Kooora final URL: {response.url}",
                    flush=True
                )

                print(
                    f"Kooora HTML length: {len(response.text)}",
                    flush=True
                )

                return response

        except Exception as e:
            print(f"Kooora connection error: {e}", flush=True)

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
    current_time = datetime.now().strftime("%H:%M:%S")

    if status_type == "FT":
        status_text = "انتهت المباراة تماماً (FT) ✅"
        title = "🚨 تنبيه: نهاية المباراة على كووورة"
    else:
        status_text = "انتهى الشوط الأول (HT) ⏸️"
        title = "🟡 تنبيه: نهاية الشوط الأول على كووورة"

    print(
        f"Checking bookmakers for: {match_name}",
        flush=True
    )

    bookmaker_results = check_all_bookmakers()

    message = (
        f"{title}\n\n"
        f"⚽ المباراة: {match_name}\n"
        f"🔢 النتيجة: {score[0]} - {score[1]}\n"
        f"🌍 الدولة: {country}\n"
        f"🏆 البطولة: {league}\n"
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
        status = bookmaker_results.get(bookmaker, "NOT_CHECKED")

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
        f"🟢 صفحات يمكن الوصول إليها: {accessible}\n"
        f"🚫 CAPTCHA: {captcha}\n"
        f"🔴 محظورة: {blocked}\n"
        f"⚪ أخرى/غير متحقق: {other}\n\n"
        "ℹ️ المنصات التي يظهر فيها CAPTCHA تم استبعادها تلقائياً.\n"
        "ℹ️ لا يتم تجاوز CAPTCHA أو تسجيل الدخول أو تنفيذ أي رهان تلقائياً."
    )

    send_telegram_message(message)

# =========================================================
# PROCESS CANDIDATE
# =========================================================

def process_candidate_text(
    text,
    country,
    league,
    seen_candidates
):
    """Process either a parsed Kooora DOM dictionary or legacy text."""
    if isinstance(text, dict):
        match_name = text.get("match_name")
        score = text.get("score")
        status = text.get("status")
        raw_text = text.get("raw", "")
        # Kooora competition context belongs to the section around the match.
        if text.get("country"):
            country = text["country"]
        if text.get("league"):
            league = text["league"]
        round_name = text.get("round")
    else:
        round_name = None
        raw_text = clean_text(text)
        if not is_real_match(raw_text):
            return 0
        status = detect_status(raw_text)
        match_name = extract_match_name(raw_text)
        score = extract_score(raw_text)

    if status not in ["FT", "HT"] or not match_name or score is None:
        return 0

    league = extract_league(raw_text, league)

    match_id = f"{match_name}|{score[0]}-{score[1]}|{status}"

    if match_id in seen_candidates or match_id in sent_alerts:
        return 0

    seen_candidates.add(match_id)

    print(
        f"🚨 REAL MATCH DETECTED: {match_name} | "
        f"{score[0]}-{score[1]} | {status}",
        flush=True
    )

    format_and_send_alert(
        match_name,
        country,
        league + (f" — {round_name}" if round_name else ""),
        status,
        score
    )

    sent_alerts.add(match_id)
    return 1

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

        title = (
            soup.title.get_text(" ", strip=True)
            if soup.title else "NO TITLE"
        )

        print(f"Kooora title: {title[:200]}", flush=True)

        country = "الدولي / محلي"
        league = "الدوري العام"
        seen_candidates = set()
        total_alerts = 0

        # =================================================
        # DEBUG FIRST
        # =================================================
        debug_kooora_structure(soup, max_scores=20)

        # =================================================
        # DOM
        # =================================================
        dom_candidates = find_dom_match_candidates(soup)

        print(
            f"Kooora REAL DOM candidates: {len(dom_candidates)}",
            flush=True
        )

        for parsed_match in dom_candidates:
            total_alerts += process_candidate_text(
                parsed_match,
                country,
                league,
                seen_candidates
            )

        # =================================================
        # SCRIPTS
        # =================================================
        script_candidates = extract_script_candidates(soup)

        print(
            f"Kooora REAL script candidates: {len(script_candidates)}",
            flush=True
        )

        for text in script_candidates:
            total_alerts += process_candidate_text(
                text,
                country,
                league,
                seen_candidates
            )

        # =================================================
        # RAW
        # =================================================
        if not dom_candidates and not script_candidates:
            raw_candidates = extract_raw_text_candidates(soup)

            print(
                f"Kooora REAL raw candidates: {len(raw_candidates)}",
                flush=True
            )

            for text in raw_candidates:
                total_alerts += process_candidate_text(
                    text,
                    country,
                    league,
                    seen_candidates
                )

        print(
            f"Kooora scan finished. "
            f"REAL alerts generated: {total_alerts}",
            flush=True
        )

        if len(sent_alerts) > 1000:
            sent_alerts.clear()
            print("sent_alerts cleared", flush=True)

    except Exception as e:
        print(f"Error scraping Kooora: {e}", flush=True)

# =========================================================
# BOT LOOP
# =========================================================

def bot_loop():
    print("🚀 BOT LOOP STARTED", flush=True)

    current_time = datetime.now().strftime("%H:%M:%S")

    startup_message = (
        "🚀 تم تشغيل بوت مراقبة كووورة بنجاح!\n\n"
        f"⏰ الوقت: {current_time}\n"
        "⚽ مراقبة FT و HT\n"
        "📊 فحص المنصات العامة\n"
        "🚫 استبعاد CAPTCHA تلقائياً\n"
        "🛡️ منع التنبيهات الوهمية\n"
        "🔄 الفحص كل 60 ثانية"
    )

    print("📨 Sending Telegram startup message...", flush=True)
    send_telegram_message(startup_message)
    print("✅ Startup message finished", flush=True)

    while True:
        try:
            print("\n==============================", flush=True)
            print("🔍 Checking Kooora...", flush=True)

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

bot_thread = threading.Thread(
    target=bot_loop,
    daemon=True
)

bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )
