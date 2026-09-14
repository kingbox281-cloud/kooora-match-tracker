import os
import re
import time
import threading
import unicodedata
from datetime import datetime
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from flask import Flask

# Playwright is optional at import time so the web server can still start
# if the browser package is not installed. For real bookmaker JS checks,
# install playwright and Chromium in the Render build command.
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False


# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

KOOORA_URL = "https://www.kooora.com/كرة القدم/مباريات-اليوم"
KOOORA_FALLBACK_URL = "https://www.kooora.com/default.aspx?g=matches"

SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "60"))
BROWSER_TIMEOUT_MS = int(os.getenv("BROWSER_TIMEOUT_MS", "20000"))
BROWSER_WAIT_MS = int(os.getenv("BROWSER_WAIT_MS", "5000"))
MAX_BROWSER_WORKERS = int(os.getenv("MAX_BROWSER_WORKERS", "3"))

BOOKMAKERS = [
    ("Tipico", "https://www.tipico.de/"),
    ("Tipwin", "https://www.tipwin.de/"),
    ("Merkur Bets", "https://www.merkurbets.de/"),
    ("sportwetten.de", "https://www.sportwetten.de/"),
    ("NEO.bet", "https://neo.bet/de/"),
    ("bet365", "https://www.bet365.com/"),
    ("Winamax", "https://www.winamax.de/"),
    ("bwin", "https://sports.bwin.de/"),
    ("Betano", "https://www.betano.de/"),
    ("Bet-at-home", "https://www.bet-at-home.com/"),
    ("ODDSET", "https://www.oddset.de/"),
    ("Interwetten", "https://www.interwetten.de/"),
    ("DAZN Bet", "https://www.daznbet.de/"),
    ("AdmiralBet", "https://www.admiralbet.de/"),
    ("Betway", "https://betway.de/"),
    ("LeoVegas", "https://www.leovegas.com/"),
    ("VBET", "https://www.vbet.de/"),
    ("Bet3000", "https://www.bet3000.com/"),
]

CAPTCHA_MARKERS = [
    "captcha", "recaptcha", "hcaptcha", "verify you are human",
    "verify human", "security check", "bot detection",
    "access denied", "cloudflare", "unusual traffic",
    "robot check", "are you a robot", "zugriff verweigert",
]

PREMATCH_MARKERS = [
    "pre-match", "prematch", "pre match", "upcoming", "not started",
    "not begun", "scheduled", "before the match", "match starts",
    "starts in", "vor dem spiel", "noch nicht begonnen", "bevorstehend",
    "kommende", "geplant", "spiel beginnt", "noch nicht gestartet",
    "قبل المباراة", "لم تبدأ", "لم تبدأ بعد", "قادمة", "مجدولة",
]

POSTMATCH_MARKERS = [
    "full time", "finished", "final", "ended", "completed",
    "beendet", "abgeschlossen", "spiel beendet", "endstand",
    "انتهت", "نهاية المباراة", "نهائي", "مكتملة",
]

ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
NON_ALNUM = re.compile(r"[^a-z0-9\u0600-\u06ff]+", re.IGNORECASE)


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return (
        "Kooora Match Tracker is running. "
        f"Browser/JS={'ON' if PLAYWRIGHT_AVAILABLE else 'OFF'}"
    )


@app.route("/health")
def health():
    return {
        "ok": True,
        "browser_js": PLAYWRIGHT_AVAILABLE,
        "scan_seconds": SCAN_SECONDS,
    }


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8,ar;q=0.7",
})


# ============================================================
# TEXT / TEAM CLEANING
# ============================================================

def clean_text(value):
    if value is None:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    value = value.replace("\xa0", " ")
    value = ARABIC_DIACRITICS.sub("", value)
    value = value.replace("ـ", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_team(value):
    """
    Creates a stable comparison form without changing the displayed name.
    Important: this removes repeated identical team names caused by Kooora
    desktop/mobile/accessibility markup, e.g.:
      'غازي عنتاب غازي عنتاب' -> 'غازي عنتاب'
    """
    value = clean_text(value)

    # Remove common score/status fragments if they accidentally enter a name.
    value = re.sub(r"\b(?:FT|HT|LIVE|RESULT|FIXTURE)\b", " ", value, flags=re.I)
    value = re.sub(r"\b\d{1,2}\s*[-:]\s*\d{1,2}\b", " ", value)

    # Remove obvious Kooora short team codes such as LIS / POR when they
    # are separate uppercase tokens. Do not remove ordinary long names.
    value = re.sub(r"\b[A-Z]{2,4}\b", " ", value)

    value = clean_text(value)
    if not value:
        return ""

    # Tokenize while retaining Arabic and Latin words.
    tokens = re.findall(r"[a-z0-9\u0600-\u06ff]+", value.lower())

    # Collapse an exact repeated sequence:
    # A B A B -> A B
    # A A -> A
    # This handles the duplicated DOM/accessibility text seen in Kooora.
    if len(tokens) >= 2:
        half = len(tokens) // 2
        if len(tokens) % 2 == 0 and tokens[:half] == tokens[half:]:
            tokens = tokens[:half]

    # Collapse adjacent duplicate tokens:
    # 'shakhtar shakhtar' -> 'shakhtar'
    collapsed = []
    for token in tokens:
        if not collapsed or token != collapsed[-1]:
            collapsed.append(token)

    return " ".join(collapsed)


def display_team(value):
    value = clean_text(value)
    if not value:
        return ""
    return value


def team_tokens(value):
    norm = normalize_team(value)
    return set(norm.split())


def meaningful_tokens(value):
    # Ignore tiny generic tokens that create false positives.
    stop = {
        "fc", "cf", "sc", "ac", "fk", "sk", "sv", "vfb", "tsv",
        "u19", "u20", "u21", "ii", "b", "a",
    }
    return {t for t in team_tokens(value) if len(t) >= 3 and t not in stop}


def team_match_score(source_name, bookmaker_text):
    """
    Conservative same-team score.
    Returns 0..1. We intentionally require multiple meaningful tokens
    for long names and exact normalized equality for short names.
    """
    a = normalize_team(source_name)
    if not a:
        return 0.0

    b = clean_text(bookmaker_text).lower()
    if not b:
        return 0.0

    b_norm = normalize_team(b)

    if a == b_norm:
        return 1.0

    # Search the normalized team phrase in the bookmaker page text.
    if len(a) >= 5 and a in b_norm:
        return 0.95

    tokens = meaningful_tokens(a)
    if not tokens:
        return 0.0

    hits = sum(1 for token in tokens if token in b_norm)
    ratio = hits / len(tokens)

    if len(tokens) >= 3:
        if ratio >= 0.8:
            return 0.9
        if ratio >= 0.6:
            return 0.72
    else:
        if ratio == 1:
            return 0.82

    return 0.0


def pair_match_score(home, away, bookmaker_text):
    """
    Both teams must be found. Order is accepted both ways because some
    bookmaker displays can reverse home/away order in text.
    """
    text = clean_text(bookmaker_text).lower()
    direct = min(
        team_match_score(home, text),
        team_match_score(away, text),
    )

    reverse = min(
        team_match_score(away, text),
        team_match_score(home, text),
    )

    return max(direct, reverse)


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if response.ok:
            print("[TELEGRAM] Sent")
            return True
        print(f"[TELEGRAM] HTTP {response.status_code}: {response.text[:300]}")
    except Exception as exc:
        print(f"[TELEGRAM] ERROR: {exc}")
    return False


# ============================================================
# KOOORA
# ============================================================

def fetch_kooora_html():
    for url in (KOOORA_URL, KOOORA_FALLBACK_URL):
        try:
            response = session.get(url, timeout=25)
            print(
                f"[KOOORA] HTTP {response.status_code} | "
                f"URL={response.url} | HTML={len(response.text)}"
            )
            if response.ok and len(response.text) > 50000:
                return response.text
        except Exception as exc:
            print(f"[KOOORA] ERROR {url}: {exc}")
    return ""


def extract_score_from_text(text):
    text = clean_text(text)
    # Prefer common score forms first.
    patterns = [
        r"(?<!\d)(\d{1,2})\s*[-:]\s*(\d{1,2})(?!\d)",
        r"(?<!\d)(\d{1,2})\s+(\d{1,2})(?!\d)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            a, b = int(match.group(1)), int(match.group(2))
            if a <= 30 and b <= 30:
                return a, b
    return None


def unique_strings(values):
    result = []
    seen = set()
    for value in values:
        key = normalize_team(value)
        if key and key not in seen:
            seen.add(key)
            result.append(display_team(value))
    return result


def extract_team_names_from_card(card, score):
    """
    Extracts candidate team names around the first score occurrence.
    The candidate list is then cleaned/deduplicated. This is deliberately
    conservative; if the DOM has several representations, the shortest
    useful unique candidate is preferred.
    """
    full = clean_text(card.get_text(" ", strip=True))
    score_text = f"{score[0]} - {score[1]}"

    before, after = full, ""
    pos = full.find(score_text)
    if pos >= 0:
        before = full[:pos]
        after = full[pos + len(score_text):]
    else:
        # Try compact score.
        compact = f"{score[0]}:{score[1]}"
        pos = full.find(compact)
        if pos >= 0:
            before = full[:pos]
            after = full[pos + len(compact):]

    def candidates(part):
        part = clean_text(part)
        part = re.sub(
            r"(?:FT|HT|LIVE|RESULT|FIXTURE|HALF TIME|FULL TIME|"
            r"الشوط الأول|نهاية المباراة|انتهت).*?$",
            "",
            part,
            flags=re.I,
        )
        part = re.sub(r"\b\d{1,2}\b", " ", part)
        part = clean_text(part)

        raw = [part]

        # Split common separators.
        raw.extend(re.split(r"\s{2,}|\s+\|\s+|\s+•\s+|[|/]", part))
        return unique_strings(raw)

    left_candidates = candidates(before)
    right_candidates = candidates(after)

    # Remove candidates that are clearly too long and contain the opposite
    # side twice. The normalizer already catches exact duplication.
    left_candidates = [
        x for x in left_candidates
        if 1 <= len(normalize_team(x).split()) <= 8
    ]
    right_candidates = [
        x for x in right_candidates
        if 1 <= len(normalize_team(x).split()) <= 8
    ]

    if not left_candidates or not right_candidates:
        return "", ""

    # Prefer candidate with fewer words; duplicated DOM strings tend to be
    # longer than the actual visible team name.
    left = min(left_candidates, key=lambda x: len(normalize_team(x).split()))
    right = min(right_candidates, key=lambda x: len(normalize_team(x).split()))

    return left, right


def parse_kooora(html):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".fco-match-list-item[data-match-status]")

    counts = {"FIXTURE": 0, "LIVE": 0, "RESULT": 0}
    matches = []

    for card in cards:
        status = clean_text(card.get("data-match-status", "")).upper()
        if status not in counts:
            continue
        counts[status] += 1

        # We need a score for HT/FT detection.
        score = extract_score_from_text(card.get_text(" ", strip=True))
        if not score:
            continue

        if status == "RESULT":
            phase = "FT"
        elif status == "LIVE":
            card_status = clean_text(
                card.select_one(".fco-match-status").get_text(" ", strip=True)
                if card.select_one(".fco-match-status") else ""
            )
            if re.search(r"\b(?:HT|HALF\s*TIME)\b|الشوط\s*الأول", card_status, re.I):
                phase = "HT"
            else:
                # Do not classify an arbitrary live score as HT.
                continue
        else:
            # Fixture is not a scored HT/FT alert.
            continue

        home, away = extract_team_names_from_card(card, score)
        home_n = normalize_team(home)
        away_n = normalize_team(away)

        if not home_n or not away_n:
            continue
        if home_n == away_n:
            continue

        matches.append({
            "home": display_team(home),
            "away": display_team(away),
            "home_norm": home_n,
            "away_norm": away_n,
            "home_tokens": meaningful_tokens(home),
            "away_tokens": meaningful_tokens(away),
            "home_score": score[0],
            "away_score": score[1],
            "phase": phase,
        })

    # Deduplicate by normalized team pair + phase + score.
    unique = {}
    for match in matches:
        key = (
            match["home_norm"],
            match["away_norm"],
            match["phase"],
            match["home_score"],
            match["away_score"],
        )
        unique[key] = match

    result = list(unique.values())

    print(
        f"[KOOORA] cards={len(cards)} | "
        f"FIXTURE={counts['FIXTURE']} | LIVE={counts['LIVE']} | "
        f"RESULT={counts['RESULT']} | HT/FT={len(result)}"
    )

    for m in result[:60]:
        print(
            f"[KOOORA] {m['phase']} "
            f"{m['home']} {m['home_score']}-{m['away_score']} {m['away']}"
        )

    return result


# ============================================================
# BOOKMAKER PAGE ANALYSIS
# ============================================================

def page_contains_marker(text, markers):
    low = clean_text(text).lower()
    return any(marker.lower() in low for marker in markers)


def classify_page(text, final_url=""):
    combined = f"{text} {final_url}".lower()

    if page_contains_marker(combined, CAPTCHA_MARKERS):
        return "CAPTCHA"

    if page_contains_marker(combined, POSTMATCH_MARKERS):
        # This does not by itself mean our target match is finished. It only
        # helps reject obvious historical/result pages.
        post = True
    else:
        post = False

    if page_contains_marker(combined, PREMATCH_MARKERS):
        return "PREMATCH"

    if post:
        return "POSTMATCH"

    return "NOT_CONFIRMED"


def browser_check_one(bookmaker, url, matches):
    """
    Opens the bookmaker homepage with a real JS-capable browser and waits
    for client-side rendering. It does NOT solve or bypass CAPTCHA/Cloudflare.
    If a protection page is detected, the result is UNKNOWN.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {
            "bookmaker": bookmaker,
            "status": "BROWSER_UNAVAILABLE",
            "final_url": url,
            "matches": [],
        }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                locale="de-DE",
                timezone_id="Europe/Berlin",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()

            try:
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=BROWSER_TIMEOUT_MS,
                )
                # Give normal JS applications time to render.
                page.wait_for_timeout(BROWSER_WAIT_MS)

                final_url = page.url
                title = page.title()
                text = page.locator("body").inner_text(timeout=5000)

                http_status = response.status if response else 0

                if page_contains_marker(
                    f"{title} {text} {final_url}",
                    CAPTCHA_MARKERS,
                ):
                    print(
                        f"[BROWSER] {bookmaker} HTTP={http_status} "
                        f"CAPTCHA/PROTECTION final={final_url}"
                    )
                    return {
                        "bookmaker": bookmaker,
                        "status": "CAPTCHA",
                        "final_url": final_url,
                        "matches": [],
                    }

                # Search the rendered page for the exact target pair.
                found = []
                for match in matches:
                    pair_score = pair_match_score(
                        match["home"],
                        match["away"],
                        text,
                    )
                    if pair_score < 0.80:
                        continue

                    # For the same rendered page, require a pre-match signal
                    # close enough to be meaningful. First use page-wide
                    # markers, then inspect text snippets around team names.
                    page_class = classify_page(text, final_url)

                    if page_class == "PREMATCH":
                        found.append({
                            "match": match,
                            "confidence": pair_score,
                            "status": "PREMATCH",
                        })
                        continue

                    # Try to find a local snippet containing both teams.
                    low = text.lower()
                    home_norm = normalize_team(match["home"])
                    away_norm = normalize_team(match["away"])

                    # Search each meaningful token and take nearby windows.
                    local_confirmed = False
                    for htoken in meaningful_tokens(match["home"]):
                        idx = low.find(htoken)
                        if idx < 0:
                            continue
                        window = low[max(0, idx - 1500): idx + 1500]
                        if all(
                            token in window
                            for token in meaningful_tokens(match["away"])
                        ):
                            if page_contains_marker(window, PREMATCH_MARKERS):
                                local_confirmed = True
                                break

                    if local_confirmed:
                        found.append({
                            "match": match,
                            "confidence": pair_score,
                            "status": "PREMATCH",
                        })

                status = "PREMATCH" if found else classify_page(text, final_url)

                print(
                    f"[BROWSER] {bookmaker} HTTP={http_status} "
                    f"{status} final={final_url} "
                    f"rendered_chars={len(text)} found={len(found)}"
                )

                return {
                    "bookmaker": bookmaker,
                    "status": status,
                    "final_url": final_url,
                    "matches": found,
                }

            finally:
                context.close()
                browser.close()

    except PlaywrightTimeoutError as exc:
        print(f"[BROWSER] {bookmaker} TIMEOUT: {exc}")
        return {
            "bookmaker": bookmaker,
            "status": "TIMEOUT",
            "final_url": url,
            "matches": [],
        }
    except Exception as exc:
        print(f"[BROWSER] {bookmaker} ERROR: {exc}")
        return {
            "bookmaker": bookmaker,
            "status": "ERROR",
            "final_url": url,
            "matches": [],
        }


def requests_check_one(bookmaker, url, matches):
    """
    Safe fallback when Playwright is unavailable.
    It never bypasses anti-bot protection.
    """
    try:
        response = session.get(url, timeout=20, allow_redirects=True)
        text = response.text
        final_url = response.url

        if page_contains_marker(
            f"{response.text} {final_url}",
            CAPTCHA_MARKERS,
        ):
            status = "CAPTCHA"
        else:
            status = classify_page(
                BeautifulSoup(text, "html.parser").get_text(" ", strip=True),
                final_url,
            )

        found = []
        if status == "PREMATCH":
            visible = BeautifulSoup(
                text, "html.parser"
            ).get_text(" ", strip=True)
            for match in matches:
                score = pair_match_score(
                    match["home"], match["away"], visible
                )
                if score >= 0.80:
                    found.append({
                        "match": match,
                        "confidence": score,
                        "status": "PREMATCH",
                    })

        print(
            f"[HTTP] {bookmaker} HTTP={response.status_code} "
            f"{status} final={final_url} found={len(found)}"
        )
        return {
            "bookmaker": bookmaker,
            "status": status,
            "final_url": final_url,
            "matches": found,
        }

    except Exception as exc:
        print(f"[HTTP] {bookmaker} ERROR: {exc}")
        return {
            "bookmaker": bookmaker,
            "status": "ERROR",
            "final_url": url,
            "matches": [],
        }


# ============================================================
# BOOKMAKER SCAN
# ============================================================

def scan_bookmakers(matches):
    results = []

    # Keep concurrency low. Chromium is much heavier than requests and
    # Render instances can run out of RAM if every bookmaker opens at once.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    worker = browser_check_one if PLAYWRIGHT_AVAILABLE else requests_check_one

    with ThreadPoolExecutor(max_workers=max(1, MAX_BROWSER_WORKERS)) as pool:
        futures = [
            pool.submit(worker, bookmaker, url, matches)
            for bookmaker, url in BOOKMAKERS
        ]
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                print(f"[BOOKMAKER] worker error: {exc}")

    return results


# ============================================================
# ALERT LOGIC
# ============================================================

sent_alerts = set()


def match_key(match):
    return (
        match["home_norm"],
        match["away_norm"],
        match["phase"],
        match["home_score"],
        match["away_score"],
    )


def send_same_match_alert(bookmaker_result, found):
    match = found["match"]
    key = (
        bookmaker_result["bookmaker"],
        match_key(match),
    )

    if key in sent_alerts:
        return

    sent_alerts.add(key)

    message = (
        "⚽ SAME MATCH PRE-MATCH\n\n"
        f"🏠 {match['home']}\n"
        f"🆚 {match['away']}\n"
        f"📊 Kooora: {match['home_score']} - {match['away_score']} "
        f"({match['phase']})\n"
        f"🎯 Bookmaker: {bookmaker_result['bookmaker']}\n"
        f"🔎 Status: PREMATCH\n"
        f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"🔗 {bookmaker_result['final_url']}"
    )

    telegram_send(message)


def process_scan():
    started = time.time()

    html = fetch_kooora_html()
    if not html:
        print("[SCAN] Kooora unavailable")
        return

    matches = parse_kooora(html)

    if not matches:
        print("[SCAN] No HT/FT matches extracted")
        return

    print(
        f"[SCAN] Checking {len(matches)} Kooora HT/FT matches "
        f"against {len(BOOKMAKERS)} bookmakers | "
        f"Browser/JS={'ON' if PLAYWRIGHT_AVAILABLE else 'OFF'}"
    )

    results = scan_bookmakers(matches)

    confirmed = 0
    for result in results:
        for found in result.get("matches", []):
            if found.get("status") == "PREMATCH":
                confirmed += 1
                send_same_match_alert(result, found)

    status_counts = {}
    for result in results:
        status = result.get("status", "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1

    elapsed = time.time() - started
    print(
        f"[SCAN] Done in {elapsed:.1f}s | "
        f"bookmaker statuses={status_counts} | "
        f"confirmed={confirmed}"
    )


def scanner_loop():
    print(
        f"[START] Kooora Match Tracker | "
        f"interval={SCAN_SECONDS}s | "
        f"Playwright={'AVAILABLE' if PLAYWRIGHT_AVAILABLE else 'NOT INSTALLED'}"
    )

    # Scan immediately, then every configured interval.
    while True:
        try:
            process_scan()
        except Exception as exc:
            print(f"[SCAN] UNHANDLED ERROR: {exc}")

        time.sleep(max(10, SCAN_SECONDS))


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))

    thread = threading.Thread(target=scanner_loop, daemon=True)
    thread.start()

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )
