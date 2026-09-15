import os
import re
import time
import threading
import unicodedata
from datetime import datetime
from urllib.parse import urljoin, urlparse, quote

import requests
from bs4 import BeautifulSoup
from flask import Flask

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False


# ============================================================
# CONFIG
# ============================================================

APP_VERSION = "KOOORA_BROWSER_V3"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

KOOORA_URL = "https://www.kooora.com/كرة القدم/مباريات-اليوم"
KOOORA_FALLBACK_URL = "https://www.kooora.com/default.aspx?g=matches"

SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "60"))
BROWSER_TIMEOUT_MS = int(os.getenv("BROWSER_TIMEOUT_MS", "20000"))
BROWSER_WAIT_MS = int(os.getenv("BROWSER_WAIT_MS", "3000"))

MAX_BROWSER_WORKERS = int(os.getenv("MAX_BROWSER_WORKERS", "2"))
MAX_EVENT_LINKS = int(os.getenv("MAX_EVENT_LINKS", "80"))
MAX_SPORT_PAGES = int(os.getenv("MAX_SPORT_PAGES", "12"))

EVENT_SEARCH_TIMEOUT_MS = int(
    os.getenv("EVENT_SEARCH_TIMEOUT_MS", "8000")
)

EVENT_PAGE_WAIT_MS = int(
    os.getenv("EVENT_PAGE_WAIT_MS", "1500")
)


# ============================================================
# BOOKMAKERS
# ============================================================

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


# ============================================================
# MARKERS
# ============================================================

CAPTCHA_MARKERS = [
    "captcha",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "verify human",
    "security check",
    "bot detection",
    "access denied",
    "cloudflare",
    "unusual traffic",
    "robot check",
    "are you a robot",
    "zugriff verweigert",
    "access denied",
]

PREMATCH_MARKERS = [
    "pre-match",
    "prematch",
    "pre match",
    "upcoming",
    "not started",
    "not begun",
    "scheduled",
    "before the match",
    "match starts",
    "starts in",
    "vor dem spiel",
    "noch nicht begonnen",
    "bevorstehend",
    "kommende",
    "geplant",
    "spiel beginnt",
    "noch nicht gestartet",
    "قبل المباراة",
    "لم تبدأ",
    "لم تبدأ بعد",
    "قادمة",
    "مجدولة",
]

POSTMATCH_MARKERS = [
    "full time",
    "finished",
    "final",
    "ended",
    "completed",
    "beendet",
    "abgeschlossen",
    "spiel beendet",
    "endstand",
    "انتهت",
    "نهاية المباراة",
    "نهائي",
    "مكتملة",
]

EVENT_URL_HINTS = [
    "match",
    "matches",
    "event",
    "events",
    "game",
    "games",
    "sport",
    "sports",
    "football",
    "soccer",
    "fussball",
    "fußball",
    "wetten",
    "wette",
    "bet",
    "bets",
    "spiel",
    "spiele",
    "live",
    "prematch",
    "pre-match",
    "veranstaltung",
    "odds",
    "quote",
]

SEARCH_URL_HINTS = [
    "search",
    "suche",
    "find",
    "finden",
]


ARABIC_DIACRITICS = re.compile(
    r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]"
)

NON_ALNUM = re.compile(
    r"[^a-z0-9\u0600-\u06ff]+",
    re.IGNORECASE,
)


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return (
        "Kooora Match Tracker is running. "
        f"Version={APP_VERSION} | "
        f"Browser/JS={'ON' if PLAYWRIGHT_AVAILABLE else 'OFF'}"
    )


@app.route("/version")
def version():
    return {
        "version": APP_VERSION,
        "browser_js": PLAYWRIGHT_AVAILABLE,
        "scan_seconds": SCAN_SECONDS,
        "max_browser_workers": MAX_BROWSER_WORKERS,
    }


@app.route("/health")
def health():
    return {
        "ok": True,
        "version": APP_VERSION,
        "browser_js": PLAYWRIGHT_AVAILABLE,
        "scan_seconds": SCAN_SECONDS,
    }


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8,ar;q=0.7",
    }
)


# ============================================================
# TEXT CLEANING
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
    value = clean_text(value)

    if not value:
        return ""

    value = re.sub(
        r"\b(?:FT|HT|LIVE|RESULT|FIXTURE|FINAL)\b",
        " ",
        value,
        flags=re.I,
    )

    value = re.sub(
        r"\b\d{1,2}\s*[-:]\s*\d{1,2}\b",
        " ",
        value,
    )

    value = re.sub(
        r"\b[A-Z]{2,4}\b",
        " ",
        value,
    )

    value = clean_text(value)

    tokens = re.findall(
        r"[a-z0-9\u0600-\u06ff]+",
        value.lower(),
    )

    if len(tokens) >= 2:
        half = len(tokens) // 2

        if (
            len(tokens) % 2 == 0
            and tokens[:half] == tokens[half:]
        ):
            tokens = tokens[:half]

    collapsed = []

    for token in tokens:
        if not collapsed or token != collapsed[-1]:
            collapsed.append(token)

    return " ".join(collapsed)


def display_team(value):
    return clean_text(value)


def team_tokens(value):
    return set(
        normalize_team(value).split()
    )


def meaningful_tokens(value):
    stop = {
        "fc",
        "cf",
        "sc",
        "ac",
        "fk",
        "sk",
        "sv",
        "vfb",
        "tsv",
        "u17",
        "u18",
        "u19",
        "u20",
        "u21",
        "ii",
        "b",
        "a",
    }

    return {
        token
        for token in team_tokens(value)
        if len(token) >= 3 and token not in stop
    }


# ============================================================
# TEAM MATCHING
# ============================================================

def team_match_score(source_name, bookmaker_text):
    source = normalize_team(source_name)

    if not source:
        return 0.0

    text = clean_text(bookmaker_text).lower()

    if not text:
        return 0.0

    normalized_text = normalize_team(text)

    if source == normalized_text:
        return 1.0

    if len(source) >= 5 and source in normalized_text:
        return 0.95

    tokens = meaningful_tokens(source)

    if not tokens:
        return 0.0

    hits = sum(
        1
        for token in tokens
        if token in normalized_text
    )

    ratio = hits / len(tokens)

    if len(tokens) >= 3:
        if ratio >= 0.8:
            return 0.90

        if ratio >= 0.6:
            return 0.72

    else:
        if ratio == 1:
            return 0.82

    return 0.0


def pair_match_score(home, away, bookmaker_text):
    text = clean_text(bookmaker_text).lower()

    home_score = team_match_score(
        home,
        text,
    )

    away_score = team_match_score(
        away,
        text,
    )

    return min(
        home_score,
        away_score,
    )


def bookmaker_text_match(home, away, text):
    return pair_match_score(
        home,
        away,
        text,
    ) >= 0.80


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN:
        print(
            "[TELEGRAM] Missing TELEGRAM_BOT_TOKEN"
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "[TELEGRAM] Missing TELEGRAM_CHAT_ID"
        )
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

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

        print(
            "[TELEGRAM] HTTP "
            f"{response.status_code}: "
            f"{response.text[:300]}"
        )

    except Exception as exc:
        print(
            f"[TELEGRAM] ERROR: {exc}"
        )

    return False


# ============================================================
# KOOORA
# ============================================================

def fetch_kooora_html():
    urls = [
        KOOORA_URL,
        KOOORA_FALLBACK_URL,
    ]

    for url in urls:
        try:
            response = session.get(
                url,
                timeout=25,
            )

            print(
                f"[KOOORA] HTTP {response.status_code} | "
                f"URL={response.url} | "
                f"HTML={len(response.text)}"
            )

            if (
                response.ok
                and len(response.text) > 50000
            ):
                return response.text

        except Exception as exc:
            print(
                f"[KOOORA] ERROR {url}: {exc}"
            )

    return ""


def extract_score_from_text(text):
    text = clean_text(text)

    patterns = [
        r"(?<!\d)(\d{1,2})\s*[-:]\s*(\d{1,2})(?!\d)",
        r"(?<!\d)(\d{1,2})\s+(\d{1,2})(?!\d)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
        )

        if match:
            a = int(match.group(1))
            b = int(match.group(2))

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
            result.append(
                display_team(value)
            )

    return result


def extract_team_names_from_card(card, score):
    full = clean_text(
        card.get_text(
            " ",
            strip=True,
        )
    )

    score_text = (
        f"{score[0]} - {score[1]}"
    )

    before = full
    after = ""

    pos = full.find(score_text)

    if pos >= 0:
        before = full[:pos]
        after = full[
            pos + len(score_text):
        ]

    else:
        compact = (
            f"{score[0]}:{score[1]}"
        )

        pos = full.find(compact)

        if pos >= 0:
            before = full[:pos]
            after = full[
                pos + len(compact):
            ]

    def candidates(part):
        part = clean_text(part)

        part = re.sub(
            r"(?:FT|HT|LIVE|RESULT|FIXTURE|"
            r"HALF TIME|FULL TIME|"
            r"الشوط الأول|نهاية المباراة|انتهت).*?$",
            "",
            part,
            flags=re.I,
        )

        part = re.sub(
            r"\b\d{1,2}\b",
            " ",
            part,
        )

        part = clean_text(part)

        raw = [part]

        raw.extend(
            re.split(
                r"\s{2,}|\s+\|\s+|\s+•\s+|[|/]",
                part,
            )
        )

        return unique_strings(raw)

    left_candidates = candidates(before)
    right_candidates = candidates(after)

    left_candidates = [
        x
        for x in left_candidates
        if 1
        <= len(normalize_team(x).split())
        <= 8
    ]

    right_candidates = [
        x
        for x in right_candidates
        if 1
        <= len(normalize_team(x).split())
        <= 8
    ]

    if (
        not left_candidates
        or not right_candidates
    ):
        return "", ""

    left = min(
        left_candidates,
        key=lambda x: len(
            normalize_team(x).split()
        ),
    )

    right = min(
        right_candidates,
        key=lambda x: len(
            normalize_team(x).split()
        ),
    )

    return left, right


def parse_kooora(html):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    cards = soup.select(
        ".fco-match-list-item[data-match-status]"
    )

    counts = {
        "FIXTURE": 0,
        "LIVE": 0,
        "RESULT": 0,
    }

    matches = []

    for card in cards:
        status = clean_text(
            card.get(
                "data-match-status",
                "",
            )
        ).upper()

        if status not in counts:
            continue

        counts[status] += 1

        score = extract_score_from_text(
            card.get_text(
                " ",
                strip=True,
            )
        )

        if not score:
            continue

        if status == "RESULT":
            phase = "FT"

        elif status == "LIVE":
            status_element = card.select_one(
                ".fco-match-status"
            )

            card_status = clean_text(
                status_element.get_text(
                    " ",
                    strip=True,
                )
                if status_element
                else ""
            )

            if re.search(
                r"\b(?:HT|HALF\s*TIME)\b|الشوط\s*الأول",
                card_status,
                flags=re.I,
            ):
                phase = "HT"
            else:
                continue

        else:
            continue

        home, away = extract_team_names_from_card(
            card,
            score,
        )

        home_norm = normalize_team(home)
        away_norm = normalize_team(away)

        if not home_norm or not away_norm:
            continue

        if home_norm == away_norm:
            continue

        matches.append(
            {
                "home": display_team(home),
                "away": display_team(away),
                "home_norm": home_norm,
                "away_norm": away_norm,
                "home_tokens": meaningful_tokens(home),
                "away_tokens": meaningful_tokens(away),
                "home_score": score[0],
                "away_score": score[1],
                "phase": phase,
            }
        )

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

    result = list(
        unique.values()
    )

    print(
        f"[KOOORA] cards={len(cards)} | "
        f"FIXTURE={counts['FIXTURE']} | "
        f"LIVE={counts['LIVE']} | "
        f"RESULT={counts['RESULT']} | "
        f"HT/FT={len(result)}"
    )

    for match in result[:60]:
        print(
            f"[KOOORA] {match['phase']} "
            f"{match['home']} "
            f"{match['home_score']}-"
            f"{match['away_score']} "
            f"{match['away']}"
        )

    return result


# ============================================================
# PAGE HELPERS
# ============================================================

def page_contains_marker(text, markers):
    low = clean_text(text).lower()

    return any(
        marker.lower() in low
        for marker in markers
    )


def is_protected_page(
    text,
    final_url="",
):
    combined = (
        f"{text} {final_url}"
    )

    return page_contains_marker(
        combined,
        CAPTCHA_MARKERS,
    )


def classify_page(
    text,
    final_url="",
):
    combined = (
        f"{text} {final_url}"
    ).lower()

    if page_contains_marker(
        combined,
        CAPTCHA_MARKERS,
    ):
        return "CAPTCHA"

    if page_contains_marker(
        combined,
        PREMATCH_MARKERS,
    ):
        return "PREMATCH"

    if page_contains_marker(
        combined,
        POSTMATCH_MARKERS,
    ):
        return "POSTMATCH"

    return "NOT_CONFIRMED"


def absolute_url(base_url, href):
    if not href:
        return ""

    try:
        return urljoin(
            base_url,
            href,
        )
    except Exception:
        return ""


def same_domain(url_a, url_b):
    try:
        host_a = urlparse(
            url_a
        ).netloc.lower()

        host_b = urlparse(
            url_b
        ).netloc.lower()

        if host_a.startswith("www."):
            host_a = host_a[4:]

        if host_b.startswith("www."):
            host_b = host_b[4:]

        return host_a == host_b

    except Exception:
        return False


def relevant_link(
    url,
    anchor_text="",
):
    combined = (
        f"{url} {anchor_text}"
    ).lower()

    return any(
        hint in combined
        for hint in EVENT_URL_HINTS
    )


def link_priority(
    url,
    anchor_text="",
    matches=None,
):
    score = 0

    combined = (
        f"{url} {anchor_text}"
    ).lower()

    if any(
        hint in combined
        for hint in SEARCH_URL_HINTS
    ):
        score += 10

    if any(
        hint in combined
        for hint in EVENT_URL_HINTS
    ):
        score += 5

    if matches:
        for match in matches:
            home_tokens = meaningful_tokens(
                match["home"]
            )

            away_tokens = meaningful_tokens(
                match["away"]
            )

            for token in (
                home_tokens | away_tokens
            ):
                if token.lower() in combined:
                    score += 15

    return score


# ============================================================
# CANDIDATE LINK DISCOVERY
# ============================================================

def collect_candidate_links(
    page,
    base_url,
    matches,
):
    candidates = []

    try:
        anchors = page.locator("a")

        count = min(
            anchors.count(),
            1000,
        )

        for index in range(count):
            try:
                element = anchors.nth(index)

                href = element.get_attribute(
                    "href"
                )

                if not href:
                    continue

                url = absolute_url(
                    base_url,
                    href,
                )

                if not url:
                    continue

                if not same_domain(
                    base_url,
                    url,
                ):
                    continue

                if url.startswith(
                    "javascript:"
                ):
                    continue

                if url.startswith(
                    "mailto:"
                ):
                    continue

                text = clean_text(
                    element.inner_text(
                        timeout=1000
                    )
                )

                if not relevant_link(
                    url,
                    text,
                ):
                    continue

                priority = link_priority(
                    url,
                    text,
                    matches,
                )

                candidates.append(
                    (
                        priority,
                        url,
                        text,
                    )
                )

            except Exception:
                continue

    except Exception as exc:
        print(
            f"[DISCOVERY] ERROR: {exc}"
        )

    unique = {}

    for priority, url, text in candidates:
        if url not in unique:
            unique[url] = (
                priority,
                url,
                text,
            )
        else:
            old = unique[url]

            if priority > old[0]:
                unique[url] = (
                    priority,
                    url,
                    text,
                )

    ordered = sorted(
        unique.values(),
        key=lambda x: x[0],
        reverse=True,
    )

    return ordered[:MAX_EVENT_LINKS]


# ============================================================
# SEARCH CONTROLS
# ============================================================

def find_search_controls(page):
    selectors = [
        "input[type='search']",
        "input[name*='search' i]",
        "input[placeholder*='search' i]",
        "input[placeholder*='suche' i]",
        "input[placeholder*='finden' i]",
        "input[placeholder*='suchen' i]",
        "input",
    ]

    found = []

    for selector in selectors:
        try:
            locator = page.locator(
                selector
            )

            count = min(
                locator.count(),
                10,
            )

            for i in range(count):
                element = locator.nth(i)

                try:
                    if not element.is_visible():
                        continue
                except Exception:
                    continue

                found.append(
                    element
                )

            if found:
                return found

        except Exception:
            continue

    return []


def search_event_in_page(
    page,
    match,
):
    search_terms = [
        match["home"],
        match["away"],
        (
            f"{match['home']} "
            f"{match['away']}"
        ),
    ]

    controls = find_search_controls(
        page
    )

    if not controls:
        return False

    for term in search_terms:
        if not term:
            continue

        for control in controls[:3]:
            try:
                control.fill(
                    term,
                    timeout=2000,
                )

                control.press(
                    "Enter",
                    timeout=2000,
                )

                page.wait_for_timeout(
                    EVENT_PAGE_WAIT_MS
                )

                text = page.locator(
                    "body"
                ).inner_text(
                    timeout=3000
                )

                if bookmaker_text_match(
                    match["home"],
                    match["away"],
                    text,
                ):
                    return True

            except Exception:
                continue

    return False


# ============================================================
# MATCH SEARCH IN RENDERED TEXT
# ============================================================

def find_matches_in_rendered_text(
    text,
    matches,
):
    results = []

    clean = clean_text(
        text
    )

    if not clean:
        return results

    for match in matches:
        score = pair_match_score(
            match["home"],
            match["away"],
            clean,
        )

        if score < 0.80:
            continue

        results.append(
            {
                "match": match,
                "confidence": score,
                "status": "FOUND",
            }
        )

    return results


# ============================================================
# LOCAL EVENT CONFIRMATION
# ============================================================

def local_prematch_confirmation(
    text,
    match,
):
    low = clean_text(
        text
    ).lower()

    home_tokens = meaningful_tokens(
        match["home"]
    )

    away_tokens = meaningful_tokens(
        match["away"]
    )

    if not home_tokens or not away_tokens:
        return False

    positions = []

    for token in home_tokens:
        start = 0

        while True:
            index = low.find(
                token.lower(),
                start,
            )

            if index < 0:
                break

            positions.append(index)
            start = index + 1

    for position in positions[:20]:
        window = low[
            max(0, position - 2000):
            position + 2000
        ]

        away_found = all(
            token.lower() in window
            for token in away_tokens
        )

        if not away_found:
            continue

        if page_contains_marker(
            window,
            PREMATCH_MARKERS,
        ):
            return True

        # Some bookmakers show only
        # a time/countdown without words.
        time_signal = re.search(
            r"\b\d{1,2}:\d{2}\b",
            window,
        )

        if time_signal:
            if not page_contains_marker(
                window,
                POSTMATCH_MARKERS,
            ):
                return True

    return False


# ============================================================
# EVENT PAGE INSPECTION
# ============================================================

def inspect_event_links(
    page,
    base_url,
    matches,
    candidates,
):
    confirmed = []
    visited = set()

    for _, url, anchor_text in candidates:
        if url in visited:
            continue

        visited.add(url)

        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=EVENT_SEARCH_TIMEOUT_MS,
            )

            page.wait_for_timeout(
                EVENT_PAGE_WAIT_MS
            )

            final_url = page.url

            title = page.title()

            text = page.locator(
                "body"
            ).inner_text(
                timeout=5000
            )

            combined = (
                f"{title} {text}"
            )

            if is_protected_page(
                combined,
                final_url,
            ):
                continue

            for match in matches:
                pair_score = pair_match_score(
                    match["home"],
                    match["away"],
                    text,
                )

                if pair_score < 0.80:
                    continue

                if local_prematch_confirmation(
                    text,
                    match,
                ):
                    confirmed.append(
                        {
                            "match": match,
                            "confidence": pair_score,
                            "status": "PREMATCH",
                            "url": final_url,
                        }
                    )

                elif page_contains_marker(
                    text,
                    PREMATCH_MARKERS,
                ):
                    confirmed.append(
                        {
                            "match": match,
                            "confidence": pair_score,
                            "status": "PREMATCH",
                            "url": final_url,
                        }
                    )

        except PlaywrightTimeoutError:
            print(
                f"[EVENT] TIMEOUT {url}"
            )

        except Exception as exc:
            print(
                f"[EVENT] ERROR {url}: {exc}"
            )

    return confirmed


# ============================================================
# BOOKMAKER BROWSER SCANNER
# ============================================================

def browser_check_one(
    bookmaker,
    url,
    matches,
):
    if not PLAYWRIGHT_AVAILABLE:
        return {
            "bookmaker": bookmaker,
            "status": "BROWSER_UNAVAILABLE",
            "final_url": url,
            "matches": [],
        }

    browser = None
    context = None

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
                viewport={
                    "width": 1440,
                    "height": 1000,
                },
                locale="de-DE",
                timezone_id="Europe/Berlin",
                user_agent=(
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )

            page = context.new_page()

            # ------------------------------------------------
            # STEP 1: OPEN HOMEPAGE
            # ------------------------------------------------

            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=BROWSER_TIMEOUT_MS,
            )

            page.wait_for_timeout(
                BROWSER_WAIT_MS
            )

            final_url = page.url
            title = page.title()

            text = page.locator(
                "body"
            ).inner_text(
                timeout=5000
            )

            http_status = (
                response.status
                if response
                else 0
            )

            combined = (
                f"{title} {text} {final_url}"
            )

            print(
                f"[BROWSER] {bookmaker} "
                f"HTTP={http_status} "
                f"URL={final_url} "
                f"TEXT={len(text)}"
            )

            # ------------------------------------------------
            # STEP 2: PROTECTION
            # ------------------------------------------------

            if is_protected_page(
                combined,
                final_url,
            ):
                print(
                    f"[BROWSER] {bookmaker} "
                    "CAPTCHA/PROTECTION"
                )

                return {
                    "bookmaker": bookmaker,
                    "status": "CAPTCHA",
                    "final_url": final_url,
                    "matches": [],
                }

            # ------------------------------------------------
            # STEP 3: FAST HOMEPAGE CHECK
            # ------------------------------------------------

            found = []

            for match in matches:
                pair_score = pair_match_score(
                    match["home"],
                    match["away"],
                    text,
                )

                if pair_score < 0.80:
                    continue

                if local_prematch_confirmation(
                    text,
                    match,
                ):
                    found.append(
                        {
                            "match": match,
                            "confidence": pair_score,
                            "status": "PREMATCH",
                            "url": final_url,
                        }
                    )

            if found:
                print(
                    f"[BROWSER] {bookmaker} "
                    f"PREMATCH homepage "
                    f"found={len(found)}"
                )

                return {
                    "bookmaker": bookmaker,
                    "status": "PREMATCH",
                    "final_url": final_url,
                    "matches": found,
                }

            # ------------------------------------------------
            # STEP 4: DISCOVER EVENT/SPORT LINKS
            # ------------------------------------------------

            candidates = collect_candidate_links(
                page,
                final_url,
                matches,
            )

            print(
                f"[DISCOVERY] {bookmaker} "
                f"candidate_links={len(candidates)}"
            )

            # ------------------------------------------------
            # STEP 5: CRAWL SPORT/EVENT PAGES
            # ------------------------------------------------

            confirmed = inspect_event_links(
                page,
                final_url,
                matches,
                candidates,
            )

            if confirmed:
                print(
                    f"[BROWSER] {bookmaker} "
                    f"PREMATCH event pages "
                    f"found={len(confirmed)}"
                )

                return {
                    "bookmaker": bookmaker,
                    "status": "PREMATCH",
                    "final_url": final_url,
                    "matches": confirmed,
                }

            # ------------------------------------------------
            # STEP 6: SEARCH FORM
            # ------------------------------------------------

            search_results = []

            for match in matches[:30]:
                try:
                    # Go back to homepage before
                    # each independent search attempt.
                    page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=BROWSER_TIMEOUT_MS,
                    )

                    page.wait_for_timeout(
                        1000
                    )

                    if is_protected_page(
                        page.locator(
                            "body"
                        ).inner_text(
                            timeout=3000
                        ),
                        page.url,
                    ):
                        break

                    found_by_search = (
                        search_event_in_page(
                            page,
                            match,
                        )
                    )

                    if not found_by_search:
                        continue

                    text_after_search = (
                        page.locator(
                            "body"
                        ).inner_text(
                            timeout=5000
                        )
                    )

                    pair_score = pair_match_score(
                        match["home"],
                        match["away"],
                        text_after_search,
                    )

                    if pair_score < 0.80:
                        continue

                    if local_prematch_confirmation(
                        text_after_search,
                        match,
                    ):
                        search_results.append(
                            {
                                "match": match,
                                "confidence": pair_score,
                                "status": "PREMATCH",
                                "url": page.url,
                            }
                        )

                except Exception as exc:
                    print(
                        f"[SEARCH] {bookmaker} "
                        f"ERROR: {exc}"
                    )

            if search_results:
                return {
                    "bookmaker": bookmaker,
                    "status": "PREMATCH",
                    "final_url": page.url,
                    "matches": search_results,
                }

            # ------------------------------------------------
            # NOTHING CONFIRMED
            # ------------------------------------------------

            status = classify_page(
                text,
                final_url,
            )

            print(
                f"[BROWSER] {bookmaker} "
                f"{status} "
                f"final={final_url}"
            )

            return {
                "bookmaker": bookmaker,
                "status": status,
                "final_url": final_url,
                "matches": [],
            }

    except PlaywrightTimeoutError as exc:
        print(
            f"[BROWSER] {bookmaker} "
            f"TIMEOUT: {exc}"
        )

        return {
            "bookmaker": bookmaker,
            "status": "TIMEOUT",
            "final_url": url,
            "matches": [],
        }

    except Exception as exc:
        print(
            f"[BROWSER] {bookmaker} "
            f"ERROR: {exc}"
        )

        return {
            "bookmaker": bookmaker,
            "status": "ERROR",
            "final_url": url,
            "matches": [],
        }

    finally:
        try:
            if context:
                context.close()
        except Exception:
            pass

        try:
            if browser:
                browser.close()
        except Exception:
            pass


# ============================================================
# HTTP FALLBACK
# ============================================================

def requests_check_one(
    bookmaker,
    url,
    matches,
):
    try:
        response = session.get(
            url,
            timeout=20,
            allow_redirects=True,
        )

        final_url = response.url

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        text = soup.get_text(
            " ",
            strip=True,
        )

        if is_protected_page(
            text,
            final_url,
        ):
            status = "CAPTCHA"

        else:
            status = classify_page(
                text,
                final_url,
            )

        found = []

        if status == "PREMATCH":
            for match in matches:
                score = pair_match_score(
                    match["home"],
                    match["away"],
                    text,
                )

                if score >= 0.80:
                    found.append(
                        {
                            "match": match,
                            "confidence": score,
                            "status": "PREMATCH",
                            "url": final_url,
                        }
                    )

        print(
            f"[HTTP] {bookmaker} "
            f"HTTP={response.status_code} "
            f"{status} "
            f"found={len(found)}"
        )

        return {
            "bookmaker": bookmaker,
            "status": status,
            "final_url": final_url,
            "matches": found,
        }

    except Exception as exc:
        print(
            f"[HTTP] {bookmaker} "
            f"ERROR: {exc}"
        )

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
    from concurrent.futures import (
        ThreadPoolExecutor,
        as_completed,
    )

    results = []

    worker = (
        browser_check_one
        if PLAYWRIGHT_AVAILABLE
        else requests_check_one
    )

    workers = max(
        1,
        MAX_BROWSER_WORKERS,
    )

    with ThreadPoolExecutor(
        max_workers=workers
    ) as pool:

        futures = [
            pool.submit(
                worker,
                bookmaker,
                url,
                matches,
            )
            for bookmaker, url
            in BOOKMAKERS
        ]

        for future in as_completed(
            futures
        ):
            try:
                result = future.result()
                results.append(result)

            except Exception as exc:
                print(
                    "[BOOKMAKER] "
                    f"worker error: {exc}"
                )

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


def send_same_match_alert(
    bookmaker_result,
    found,
):
    match = found["match"]

    key = (
        bookmaker_result["bookmaker"],
        match_key(match),
    )

    if key in sent_alerts:
        return

    message = (
        "⚽ SAME MATCH PRE-MATCH\n\n"
        f"🏠 {match['home']}\n"
        f"🆚 {match['away']}\n"
        f"📊 Kooora: "
        f"{match['home_score']} - "
        f"{match['away_score']} "
        f"({match['phase']})\n"
        f"🎯 Bookmaker: "
        f"{bookmaker_result['bookmaker']}\n"
        f"🔎 Status: PREMATCH\n"
        f"🎯 Confidence: "
        f"{found.get('confidence', 0):.2f}\n"
        f"🕒 "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"🔗 "
        f"{found.get('url') or bookmaker_result.get('final_url', '')}"
    )

    success = telegram_send(
        message
    )

    if success:
        sent_alerts.add(key)


# ============================================================
# SCAN PROCESS
# ============================================================

def process_scan():
    started = time.time()

    html = fetch_kooora_html()

    if not html:
        print(
            "[SCAN] Kooora unavailable"
        )
        return

    matches = parse_kooora(
        html
    )

    if not matches:
        print(
            "[SCAN] No HT/FT matches extracted"
        )
        return

    print(
        f"[SCAN] Checking "
        f"{len(matches)} Kooora HT/FT matches "
        f"against "
        f"{len(BOOKMAKERS)} bookmakers | "
        f"Browser/JS="
        f"{'ON' if PLAYWRIGHT_AVAILABLE else 'OFF'}"
    )

    results = scan_bookmakers(
        matches
    )

    confirmed = 0

    status_counts = {}

    for result in results:
        status = result.get(
            "status",
            "UNKNOWN",
        )

        status_counts[status] = (
            status_counts.get(
                status,
                0,
            )
            + 1
        )

        for found in result.get(
            "matches",
            [],
        ):
            if found.get(
                "status"
            ) == "PREMATCH":

                confirmed += 1

                send_same_match_alert(
                    result,
                    found,
                )

    elapsed = (
        time.time() - started
    )

    print(
        f"[SCAN] Done in "
        f"{elapsed:.1f}s | "
        f"bookmaker statuses="
        f"{status_counts} | "
        f"confirmed="
        f"{confirmed}"
    )


# ============================================================
# SCANNER LOOP
# ============================================================

def scanner_loop():
    print(
        f"[START] {APP_VERSION} | "
        f"Kooora Match Tracker | "
        f"interval={SCAN_SECONDS}s | "
        f"Playwright="
        f"{'AVAILABLE' if PLAYWRIGHT_AVAILABLE else 'NOT INSTALLED'}"
    )

    if not TELEGRAM_BOT_TOKEN:
        print(
            "[START] WARNING: "
            "TELEGRAM_BOT_TOKEN is missing"
        )

    if not TELEGRAM_CHAT_ID:
        print(
            "[START] WARNING: "
            "TELEGRAM_CHAT_ID is missing"
        )

    while True:
        try:
            process_scan()

        except Exception as exc:
            print(
                f"[SCAN] UNHANDLED ERROR: {exc}"
            )

        time.sleep(
            max(
                10,
                SCAN_SECONDS,
            )
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    port = int(
        os.getenv(
            "PORT",
            "10000",
        )
    )

    thread = threading.Thread(
        target=scanner_loop,
        daemon=True,
    )

    thread.start()

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )
