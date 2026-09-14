import os
import time
import threading
import re
import requests
from datetime import datetime
from flask import Flask
from bs4 import BeautifulSoup


# =========================================================
# FLASK
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
    if (
        not TELEGRAM_BOT_TOKEN
        or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN"
    ):
        print("Telegram token is not configured.", flush=True)
        return None

    if (
        not TELEGRAM_CHAT_ID
        or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID"
    ):
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
                "text": message,
            },
            timeout=15,
        )

        print(
            f"Telegram response: {response.status_code}",
            flush=True,
        )

        try:
            return response.json()
        except Exception:
            return {
                "status_code": response.status_code
            }

    except requests.exceptions.RequestException as e:
        print(
            f"Telegram connection error: {e}",
            flush=True,
        )
        return None

    except Exception as e:
        print(
            f"Telegram unexpected error: {e}",
            flush=True,
        )
        return None


# =========================================================
# KOOORA
# =========================================================

KOOORA_URL = (
    "https://www.kooora.com/"
    "%D9%83%D8%B1%D8%A9-%D8%A7%D9%84%D9%82%D8%AF%D9%85/"
    "%D9%85%D8%A8%D8%A7%D8%B1%D9%8A%D8%A7%D8%AA-%D8%A7%D9%84%D9%8A%D9%88%D9%85"
)

KOOORA_FALLBACK_URL = (
    "https://www.kooora.com/default.aspx?g=matches"
)


KOOORA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,"
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
    "Bet3000",
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
    "captcha",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "verify that you are human",
    "are you human",
    "security check",
    "bot detection",
    "access denied",
    "cloudflare",
]


# =========================================================
# BOOKMAKER MATCH CHECK
# =========================================================

# We do NOT treat an accessible homepage as proof that the same
# match is still pre-match.  A bookmaker is confirmed only when
# BOTH teams are found together in the same page/container and
# that container also contains a pre-match marker.
PREMATCH_MARKERS = [
    "pre-match", "prematch", "pre match",
    "upcoming", "not started", "not begun", "scheduled",
    "before the match", "match starts", "starts in",
    "vor dem spiel", "nicht begonnen", "noch nicht gestartet",
    "bevorstehend", "spielbeginn",
    "لم تبدأ", "لم تبدأ بعد", "قبل المباراة", "قبل بداية المباراة",
    "قبل البداية", "لم تبدأ المباراة", "لم تبدأ بعد",
]

POSTMATCH_MARKERS = [
    "finished", "full time", "final", "ended", "completed",
    "beendet", "ende", "endstand", "abgeschlossen",
    "انتهت", "النهاية", "نهاية المباراة", "مكتملة",
]


def normalize_match_text(text):
    """Normalize text for conservative team-name comparison."""
    if not text:
        return ""

    text = clean_text(text).lower()

    # Arabic normalization.
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    text = text.replace("أ", "ا")
    text = text.replace("إ", "ا")
    text = text.replace("آ", "ا")
    text = text.replace("ى", "ي")
    text = text.replace("ة", "ه")
    text = text.replace("ـ", "")

    # Common punctuation/separators.
    text = re.sub(r"[|/\\:;,.()\[\]{}\-_–—]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def team_tokens(team):
    """Return meaningful tokens while keeping matching conservative."""
    normalized = normalize_match_text(team)
    if not normalized:
        return set()

    # Remove common club abbreviations only when they are standalone.
    tokens = normalized.split()
    ignored = {
        "fc", "cf", "sc", "afc", "fk", "sv", "sk", "ac",
        "ks", "nk", "bk", "cd", "ud", "rc", "ca", "ss",
        "1", "2",
    }
    return {t for t in tokens if t not in ignored and len(t) >= 2}


def teams_match(container_text, team1, team2):
    """Check that both teams are represented in one bookmaker container."""
    hay = normalize_match_text(container_text)
    if not hay:
        return False

    for team in (team1, team2):
        tokens = team_tokens(team)
        if not tokens:
            return False

        # Exact normalized team string is strongest.
        exact = normalize_match_text(team)
        if exact and exact in hay:
            continue

        # Otherwise require all meaningful tokens for short names,
        # or a strong majority for longer names.
        present = sum(1 for token in tokens if token in hay)
        required = len(tokens) if len(tokens) <= 2 else max(2, int(len(tokens) * 0.75 + 0.5))
        if present < required:
            return False

    return True


def has_prematch_marker(text):
    normalized = normalize_match_text(text)
    return any(marker in normalized for marker in PREMATCH_MARKERS)


def has_postmatch_marker(text):
    normalized = normalize_match_text(text)
    return any(marker in normalized for marker in POSTMATCH_MARKERS)


def inspect_bookmaker_html(bookmaker, response, team1, team2):
    """
    Search the returned HTML for the SAME match and a pre-match marker.

    Important limitation: many bookmakers render event data with
    JavaScript.  If the teams are not present in the HTML returned by
    requests, the result is NOT_CONFIRMED rather than a false alert.
    """
    if detect_captcha(response):
        return {
            "status": "CAPTCHA",
            "url": response.url,
            "evidence": "",
        }

    if response.status_code in (401, 403, 429):
        return {
            "status": "BLOCKED",
            "url": response.url,
            "evidence": "",
        }

    if response.status_code >= 500:
        return {
            "status": "SERVER_ERROR",
            "url": response.url,
            "evidence": "",
        }

    if response.status_code != 200:
        return {
            "status": "NOT_CHECKED",
            "url": response.url,
            "evidence": "",
        }

    soup = BeautifulSoup(response.text, "html.parser")

    # Check increasingly broad containers.  We deliberately do not
    # compare the two team names against the whole homepage because
    # that can create false matches between unrelated events.
    selectors = [
        "article",
        "li",
        "tr",
        "[class*='event']",
        "[class*='match']",
        "[class*='fixture']",
        "[class*='game']",
        "[class*='sport']",
        "[data-event-id]",
        "[data-event]",
        "[data-fixture-id]",
        "[data-match-id]",
    ]

    checked = set()
    candidates = []

    for selector in selectors:
        try:
            elements = soup.select(selector)
        except Exception:
            continue

        for element in elements:
            # Avoid repeatedly checking identical DOM nodes through
            # overlapping selectors.
            marker = id(element)
            if marker in checked:
                continue
            checked.add(marker)

            text = clean_text(element.get_text(" ", strip=True))
            if not text or len(text) > 2500:
                continue

            if teams_match(text, team1, team2):
                candidates.append(text)

    # Prefer the smallest matching containers because they are more
    # likely to represent one event rather than a whole league list.
    candidates.sort(key=len)

    for text in candidates:
        if has_postmatch_marker(text):
            continue
        if has_prematch_marker(text):
            return {
                "status": "SAME_MATCH_PREMATCH",
                "url": response.url,
                "evidence": text[:500],
            }

    # As a last conservative check, inspect links whose visible text
    # itself contains both teams.  This helps on simpler bookmaker pages.
    for link in soup.find_all("a"):
        text = clean_text(link.get_text(" ", strip=True))
        if not text or len(text) > 1200:
            continue
        if teams_match(text, team1, team2) and has_prematch_marker(text):
            return {
                "status": "SAME_MATCH_PREMATCH",
                "url": response.url,
                "evidence": text[:500],
            }

    return {
        "status": "NOT_CONFIRMED",
        "url": response.url,
        "evidence": "",
    }


def check_bookmaker_match(bookmaker, team1, team2):
    url = BOOKMAKER_URLS.get(bookmaker)

    if not url:
        return {
            "status": "NOT_CHECKED",
            "url": "",
            "evidence": "",
        }

    headers = {
        "User-Agent": KOOORA_HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": url,
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=12,
            allow_redirects=True,
        )

        result = inspect_bookmaker_html(
            bookmaker,
            response,
            team1,
            team2,
        )

        print(
            f"{bookmaker}: HTTP {response.status_code} "
            f"{result['status']} {response.url}",
            flush=True,
        )

        if result["status"] == "SAME_MATCH_PREMATCH":
            print(
                f"✅ SAME MATCH PRE-MATCH: {bookmaker} | "
                f"{team1} vs {team2}",
                flush=True,
            )

        return result

    except requests.exceptions.Timeout:
        print(f"{bookmaker}: timeout", flush=True)
        return {
            "status": "TIMEOUT",
            "url": url,
            "evidence": "",
        }

    except requests.exceptions.RequestException as e:
        print(f"{bookmaker}: {e}", flush=True)
        return {
            "status": "ERROR",
            "url": url,
            "evidence": "",
        }

    except Exception as e:
        print(f"{bookmaker}: unexpected error: {e}", flush=True)
        return {
            "status": "ERROR",
            "url": url,
            "evidence": "",
        }


def check_all_bookmakers_for_match(team1, team2):
    """Check every configured bookmaker for this exact match."""
    results = {}

    for bookmaker in TARGET_BOOKMAKERS:
        results[bookmaker] = check_bookmaker_match(
            bookmaker,
            team1,
            team2,
        )
        time.sleep(0.5)

    return results


def bookmaker_status_icon(status):
    icons = {
        "SAME_MATCH_PREMATCH": "🚨 نفس المباراة ما زالت لم تبدأ",
        "NOT_CONFIRMED": "⚪ نفس المباراة غير مؤكدة",
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

sent_alerts = set()


# =========================================================
# TEXT HELPERS
# =========================================================

def clean_text(text):
    if not text:
        return ""

    text = str(text)

    text = text.replace("\xa0", " ")
    text = text.replace("\\u00a0", " ")
    text = text.replace("\\/", "/")

    arabic_numbers = str.maketrans(
        "٠١٢٣٤٥٦٧٨٩"
        "۰۱۲۳۴۵۶۷۸۹",
        "0123456789"
        "0123456789",
    )

    text = text.translate(arabic_numbers)

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


FT_RE = re.compile(
    r"انتهت|إنتهت|النهاية|نهاية المباراة|"
    r"\bFT\b|FULL[\s_-]*TIME",
    re.IGNORECASE,
)


HT_RE = re.compile(
    r"استراحة|نهاية الشوط|الشوط الأول|الشوط الاول|"
    r"بين الشوطين|\bHT\b|HALF[\s_-]*TIME",
    re.IGNORECASE,
)


# IMPORTANT:
# This regex is used ONLY inside a real RESULT/LIVE
# Kooora match card and NEVER on FIXTURE cards.
SINGLE_SCORE_RE = re.compile(
    r"(?<!\d)(\d{1,2})(?!\d)"
)


# =========================================================
# KOOORA COMPETITION CONTEXT
# =========================================================

def extract_competition_context(match_element):
    result = {
        "country": "الدولي / محلي",
        "league": "الدوري العام",
        "round": None,
    }

    section = None
    parent = match_element.parent

    for _ in range(10):
        if parent is None:
            break

        classes = " ".join(
            parent.get("class", [])
        )

        if (
            "match-list_livescores-match-list__section"
            in classes
        ):
            section = parent
            break

        parent = parent.parent

    if section is None:
        return result

    text = clean_text(
        section.get_text(
            " ",
            strip=True,
        )
    )

    round_match = re.search(
        r"الجولة\s*[:\-]?\s*(\d+)",
        text,
        re.IGNORECASE,
    )

    if round_match:
        result["round"] = (
            f"الجولة {round_match.group(1)}"
        )

        prefix = text[
            :round_match.start()
        ].strip()

    else:
        prefix = text

    countries = [
        "جنوب أفريقيا",
        "كوريا الجنوبية",
        "ساحل العاج",
        "نيجيريا",
        "اليابان",
        "جورجيا",
        "إيطاليا",
        "إسبانيا",
        "ألمانيا",
        "فرنسا",
        "إنجلترا",
        "هولندا",
        "بلجيكا",
        "البرتغال",
        "البرازيل",
        "الأرجنتين",
        "المكسيك",
        "أمريكا",
        "مصر",
        "العراق",
        "السعودية",
        "الإمارات",
        "قطر",
        "الكويت",
        "البحرين",
        "الأردن",
        "المغرب",
        "الجزائر",
        "تونس",
        "ليبيا",
        "سوريا",
        "لبنان",
        "فلسطين",
        "تركيا",
        "الصين",
        "أستراليا",
        "الهند",
        "غانا",
        "السنغال",
        "الكاميرون",
        "مالي",
        "زامبيا",
        "تنزانيا",
        "أوغندا",
        "كينيا",
    ]

    found_country = False

    for country in sorted(
        countries,
        key=len,
        reverse=True,
    ):
        if country in prefix:
            result["country"] = country

            league = prefix.replace(
                country,
                "",
            ).strip()

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
    Parse one real Kooora match.

    IMPORTANT:
    FIXTURE cards are ignored BEFORE score extraction.

    Therefore a fixture such as:

        ليدز يونايتد ليدز نيوكاسل يونايتد نيوكاسل 15:00

    can NEVER become:

        15 - 0

    Only RESULT and LIVE cards are processed.
    """

    data_status = str(
        match_element.get(
            "data-match-status",
            "",
        )
    ).upper().strip()

    # -----------------------------------------------------
    # CRITICAL FILTER
    # -----------------------------------------------------
    #
    # FIXTURE = future match
    # RESULT  = finished match
    # LIVE    = currently live / halftime
    #
    # We completely ignore every other status.
    #
    if data_status not in {
        "RESULT",
        "LIVE",
    }:
        return None

    status_element = match_element.select_one(
        ".fco-match-status"
    )

    status_text = clean_text(
        status_element.get_text(
            " ",
            strip=True,
        )
        if status_element
        else ""
    )

    # -----------------------------------------------------
    # RESULT
    # -----------------------------------------------------

    if data_status == "RESULT":
        status = "FT"

    # -----------------------------------------------------
    # LIVE
    # -----------------------------------------------------

    elif data_status == "LIVE":

        # We only want halftime.
        if HT_RE.search(status_text):
            status = "HT"
        else:
            return None

    else:
        return None

    # -----------------------------------------------------
    # BASIC MATCH DATA
    # -----------------------------------------------------

    basic = match_element.select_one(
        ".fco-match-basic-data"
    )

    if basic is None:
        return None

    basic_text = clean_text(
        basic.get_text(
            " ",
            strip=True,
        )
    )

    if not basic_text:
        return None

    # -----------------------------------------------------
    # SCORE EXTRACTION
    # -----------------------------------------------------
    #
    # This happens ONLY after RESULT/LIVE filtering.
    #
    numbers = list(
        SINGLE_SCORE_RE.finditer(
            basic_text
        )
    )

    if len(numbers) < 2:
        print(
            f"⚠️ Could not find score: "
            f"{basic_text}",
            flush=True,
        )
        return None

    first_score = numbers[0]
    second_score = numbers[1]

    try:
        score1 = int(
            first_score.group(1)
        )

        score2 = int(
            second_score.group(1)
        )

    except ValueError:
        return None

    # -----------------------------------------------------
    # TEAM NAMES
    # -----------------------------------------------------

    team1 = basic_text[
        :first_score.start()
    ].strip()

    team2 = basic_text[
        first_score.end():
        second_score.start()
    ].strip()

    # Remove short Kooora team code:
    #
    # NIG
    # PLU
    # FCO
    # EHF
    #
    team1 = re.sub(
        r"\s+\b[A-Z]{2,5}\b\s*$",
        "",
        team1,
    ).strip()

    team2 = re.sub(
        r"\s+\b[A-Z]{2,5}\b\s*$",
        "",
        team2,
    ).strip()

    # Remove accidental status text.
    team1 = FT_RE.sub(
        " ",
        team1,
    )

    team1 = HT_RE.sub(
        " ",
        team1,
    )

    team2 = FT_RE.sub(
        " ",
        team2,
    )

    team2 = HT_RE.sub(
        " ",
        team2,
    )

    team1 = clean_text(team1)
    team2 = clean_text(team2)

    if not team1 or not team2:
        return None

    if team1 == team2:
        return None

    # -----------------------------------------------------
    # MATCH LINK
    # -----------------------------------------------------

    link = match_element.select_one(
        "a.fco-match-data"
    )

    href = ""

    if link is not None:
        href = str(
            link.get(
                "href",
                "",
            )
        ).strip()

    # Stable identity.
    match_key = (
        href
        or f"{team1}|{team2}"
    )

    # -----------------------------------------------------
    # COMPETITION
    # -----------------------------------------------------

    context = extract_competition_context(
        match_element
    )

    # -----------------------------------------------------
    # RETURN
    # -----------------------------------------------------

    return {
        "match_key": match_key,
        "match_name": (
            f"{team1} vs {team2}"
        ),
        "team1": team1,
        "team2": team2,
        "score": (
            score1,
            score2,
        ),
        "status": status,
        "country": context["country"],
        "league": context["league"],
        "round": context["round"],
        "raw": clean_text(
            match_element.get_text(
                " ",
                strip=True,
            )
        ),
    }


# =========================================================
# FIND TODAY'S MATCHES
# =========================================================

def find_kooora_matches(soup):
    """
    Read ALL match cards from Kooora's today page.

    Returns:

        all_today_matches
        alert_matches

    FIXTURE cards are counted but NEVER parsed
    for score/alerts.
    """

    items = soup.select(
        ".fco-match-list-item[data-match-status]"
    )

    all_today_matches = []
    alert_matches = []

    seen_match_keys = set()

    for item in items:

        data_status = str(
            item.get(
                "data-match-status",
                "",
            )
        ).upper().strip()

        basic = item.select_one(
            ".fco-match-basic-data"
        )

        if basic is None:
            continue

        raw_basic = clean_text(
            basic.get_text(
                " ",
                strip=True,
            )
        )

        # -------------------------------------------------
        # IDENTIFY CARD ONLY
        # -------------------------------------------------
        #
        # We DO NOT extract scores here.
        #
        # This is important because fixtures contain times
        # such as 15:00.
        #

        href_element = item.select_one(
            "a.fco-match-data"
        )

        href = (
            str(
                href_element.get(
                    "href",
                    "",
                )
            ).strip()
            if href_element
            else ""
        )

        card_key = (
            href
            or raw_basic
        )

        if card_key in seen_match_keys:
            continue

        seen_match_keys.add(card_key)

        # Store card information.
        all_today_matches.append(
            {
                "key": card_key,
                "data_status": data_status,
                "raw": raw_basic,
            }
        )

        # -------------------------------------------------
        # ONLY RESULT/LIVE GO TO PARSER
        # -------------------------------------------------

        if data_status not in {
            "RESULT",
            "LIVE",
        }:
            continue

        parsed = parse_kooora_match_element(
            item
        )

        if parsed:
            alert_matches.append(parsed)

    return (
        all_today_matches,
        alert_matches,
    )


# =========================================================
# GET KOOORA PAGE
# =========================================================

def get_kooora_page():

    urls = [
        KOOORA_URL,
        KOOORA_FALLBACK_URL,
    ]

    for url in urls:

        try:

            response = requests.get(
                url,
                headers=KOOORA_HEADERS,
                timeout=20,
                allow_redirects=True,
            )

            print(
                f"Kooora response: "
                f"{response.status_code} - {url}",
                flush=True,
            )

            if response.status_code == 200:

                print(
                    f"Kooora final URL: "
                    f"{response.url}",
                    flush=True,
                )

                print(
                    f"Kooora HTML length: "
                    f"{len(response.text)}",
                    flush=True,
                )

                return response

        except requests.exceptions.RequestException as e:

            print(
                f"Kooora connection error: {e}",
                flush=True,
            )

        except Exception as e:

            print(
                f"Kooora unexpected error: {e}",
                flush=True,
            )

    return None


# =========================================================
# FORMAT TELEGRAM ALERT
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
        title = "🚨 تنبيه: نفس المباراة انتهت على كووورة"
        status_text = "انتهت المباراة تماماً (FT) ✅"
    else:
        title = "🟡 تنبيه: نفس المباراة بين الشوطين على كووورة"
        status_text = "انتهى الشوط الأول (HT) ⏸️"

    print(
        f"🔎 Checking SAME MATCH on bookmakers: {match_name}",
        flush=True,
    )

    bookmaker_results = check_all_bookmakers_for_match(
        match["team1"],
        match["team2"],
    )

    confirmed = [
        bookmaker
        for bookmaker in TARGET_BOOKMAKERS
        if bookmaker_results.get(bookmaker, {}).get("status")
        == "SAME_MATCH_PREMATCH"
    ]

    # Do not send anything unless at least one bookmaker contains
    # the same two teams and explicitly indicates a pre-match state.
    if not confirmed:
        print(
            f"ℹ️ No SAME_MATCH_PREMATCH confirmation for {match_name}. "
            "No Telegram alert sent.",
            flush=True,
        )
        return False

    message = (
        f"{title}\n\n"
        f"⚽ المباراة: {match_name}\n"
        f"🔢 النتيجة على كووورة: {score[0]} - {score[1]}\n"
        f"🌍 الدولة: {country}\n"
        f"🏆 البطولة: {league}"
    )

    if round_name:
        message += f" — {round_name}"

    message += (
        f"\n⏰ وقت التحديث: {current_time}\n\n"
        f"🛑 حالة كووورة:\n{status_text}\n\n"
        "🚨 نفس المباراة ما زالت Pre-match في:\n"
    )

    for bookmaker in confirmed:
        message += f"• {bookmaker}\n"

    message += (
        "\n⚠️ تم تأكيد الفريقين داخل نفس عنصر المباراة مع وجود "
        "علامة تدل على أن المباراة لم تبدأ.\n"
        "⚠️ إذا كانت المنصة تعتمد JavaScript ولا تُظهر المباراة في HTML، "
        "فلن يتم اعتبارها مؤكدة ولن يُرسل تنبيه خاطئ.\n"
        "ℹ️ لا يتم تجاوز CAPTCHA أو تسجيل الدخول أو تنفيذ أي رهان تلقائياً."
    )

    send_telegram_message(message)
    return True


# =========================================================
# PROCESS KOOORA ALERTS
# =========================================================

def process_kooora_alerts(alert_matches):
    date_key = datetime.now().strftime("%Y-%m-%d")
    alerts_generated = 0

    for match in alert_matches:
        alert_key = (
            f"{date_key}|"
            f"{match['match_key']}|"
            f"{match['status']}"
        )

        # Prevent duplicate processing of the same Kooora state.
        if alert_key in sent_alerts:
            continue

        print(
            "🚨 REAL MATCH DETECTED: "
            f"{match['match_name']} | "
            f"{match['score'][0]}-"
            f"{match['score'][1]} | "
            f"{match['status']}",
            flush=True,
        )

        sent = format_and_send_alert(
            match,
            date_key,
        )

        # IMPORTANT: remember the alert only after a real bookmaker
        # confirmation.  If there is no confirmation now, the match
        # will be checked again on the next 60-second cycle.
        if sent:
            sent_alerts.add(alert_key)
            alerts_generated += 1
        else:
            print(
                "⏳ No bookmaker confirmation yet; "
                "will check this match again next cycle.",
                flush=True,
            )

    return alerts_generated


# =========================================================
# MAIN KOOORA CHECK
# =========================================================

def check_kooora_matches():

    response = get_kooora_page()

    if response is None:

        print(
            "❌ Unable to access Kooora",
            flush=True,
        )

        return

    try:

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        title = (
            soup.title.get_text(
                " ",
                strip=True,
            )
            if soup.title
            else "NO TITLE"
        )

        print(
            f"Kooora title: "
            f"{title[:200]}",
            flush=True,
        )

        (
            all_matches,
            alert_matches,
        ) = find_kooora_matches(
            soup
        )

        # -------------------------------------------------
        # TODAY'S TOTAL MATCH CARDS
        # -------------------------------------------------

        print(
            "📅 Kooora TODAY match cards "
            f"found: {len(all_matches)}",
            flush=True,
        )

        # -------------------------------------------------
        # STATUS COUNTS
        # -------------------------------------------------

        fixture_count = sum(
            1
            for match in all_matches
            if match["data_status"]
            == "FIXTURE"
        )

        live_count = sum(
            1
            for match in all_matches
            if match["data_status"]
            == "LIVE"
        )

        result_count = sum(
            1
            for match in all_matches
            if match["data_status"]
            == "RESULT"
        )

        print(
            f"   FIXTURE={fixture_count} | "
            f"LIVE={live_count} | "
            f"RESULT={result_count}",
            flush=True,
        )

        print(
            "⚽ Kooora HT/FT matches "
            f"ready for checking: "
            f"{len(alert_matches)}",
            flush=True,
        )

        # -------------------------------------------------
        # DEBUG ONLY FOR REAL MATCHES
        # -------------------------------------------------

        for match in alert_matches:

            print(
                "   REAL: "
                f"{match['team1']} "
                f"{match['score'][0]}-"
                f"{match['score'][1]} "
                f"{match['team2']} "
                f"[{match['status']}]",
                flush=True,
            )

        # -------------------------------------------------
        # PROCESS
        # -------------------------------------------------

        total_alerts = (
            process_kooora_alerts(
                alert_matches
            )
        )

        print(
            "✅ Kooora scan finished. "
            f"New alerts generated: "
            f"{total_alerts}",
            flush=True,
        )

        # -------------------------------------------------
        # MEMORY LIMIT
        # -------------------------------------------------

        if len(sent_alerts) > 5000:

            sent_alerts.clear()

            print(
                "sent_alerts cleared",
                flush=True,
            )

    except Exception as e:

        print(
            f"❌ Error scraping Kooora: {e}",
            flush=True,
        )


# =========================================================
# BOT LOOP
# =========================================================

def bot_loop():

    print(
        "🚀 BOT LOOP STARTED",
        flush=True,
    )

    current_time = datetime.now().strftime(
        "%H:%M:%S"
    )

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

    print(
        "📨 Sending Telegram startup message...",
        flush=True,
    )

    send_telegram_message(
        startup_message
    )

    print(
        "✅ Startup message finished",
        flush=True,
    )

    while True:

        try:

            print(
                "\n==============================",
                flush=True,
            )

            print(
                "🔍 Checking ALL TODAY'S "
                "Kooora matches...",
                flush=True,
            )

            check_kooora_matches()

            print(
                "✅ Kooora check finished",
                flush=True,
            )

            print(
                "⏳ Next check in 60 seconds...",
                flush=True,
            )

            print(
                "==============================\n",
                flush=True,
            )

        except Exception as e:

            print(
                f"❌ Bot loop error: {e}",
                flush=True,
            )

        time.sleep(60)


# =========================================================
# START BOT THREAD
# =========================================================

bot_thread = threading.Thread(
    target=bot_loop,
    daemon=True,
)

bot_thread.start()


# =========================================================
# RUN FLASK
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "8080",
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )
