from pathlib import Path

code = r'''import os
import re
import time
import threading
import unicodedata
from datetime import datetime
from urllib.parse import urljoin, urlparse

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

APP_VERSION = "KOOORA_BROWSER_V3_1"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

KOOORA_URL = "https://www.kooora.com/كرة القدم/مباريات-اليوم"
KOOORA_FALLBACK_URL = "https://www.kooora.com/default.aspx?g=matches"

SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "60"))
BROWSER_TIMEOUT_MS = int(os.getenv("BROWSER_TIMEOUT_MS", "20000"))
BROWSER_WAIT_MS = int(os.getenv("BROWSER_WAIT_MS", "2500"))

MAX_BROWSER_WORKERS = int(os.getenv("MAX_BROWSER_WORKERS", "2"))
MAX_EVENT_LINKS = int(os.getenv("MAX_EVENT_LINKS", "60"))
MAX_SPORT_PAGES = int(os.getenv("MAX_SPORT_PAGES", "8"))
MAX_SEARCH_MATCHES = int(os.getenv("MAX_SEARCH_MATCHES", "20"))

EVENT_SEARCH_TIMEOUT_MS = int(os.getenv("EVENT_SEARCH_TIMEOUT_MS", "7000"))
EVENT_PAGE_WAIT_MS = int(os.getenv("EVENT_PAGE_WAIT_MS", "1200"))

SCANNER_RUNNING = False


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
    "captcha", "recaptcha", "hcaptcha",
    "verify you are human", "verify human",
    "security check", "bot detection",
    "access denied", "cloudflare",
    "unusual traffic", "robot check",
    "are you a robot", "zugriff verweigert",
]

PREMATCH_MARKERS = [
    "pre-match", "prematch", "pre match",
    "upcoming", "not started", "not begun",
    "scheduled", "before the match", "match starts",
    "starts in", "vor dem spiel",
    "noch nicht begonnen", "bevorstehend",
    "kommende", "geplant", "spiel beginnt",
    "noch nicht gestartet",
    "قبل المباراة", "لم تبدأ", "لم تبدأ بعد",
    "قادمة", "مجدولة",
]

POSTMATCH_MARKERS = [
    "full time", "finished", "final", "ended",
    "completed", "beendet", "abgeschlossen",
    "spiel beendet", "endstand",
    "انتهت", "نهاية المباراة", "نهائي", "مكتملة",
]

LIVE_MARKERS = [
    "live", "in play", "live now", "running",
    "läuft", "im spiel", "spiel läuft",
    "مباشر", "جاري", "الآن",
]

EVENT_URL_HINTS = [
    "match", "matches", "event", "events",
    "game", "games", "sport", "sports",
    "football", "soccer", "fussball", "fußball",
    "wetten", "wette", "bet", "bets",
    "spiel", "spiele", "live", "prematch",
    "pre-match", "veranstaltung", "odds", "quote",
]

SEARCH_URL_HINTS = [
    "search", "suche", "find", "finden",
]

# Only remove these as football naming prefixes.
# Do NOT remove every 2-4 character word.
TEAM_STOPWORDS = {
    "fc", "cf", "sc", "ac", "afc", "fk", "sk", "sv",
    "vfb", "tsv", "bsc", "cfc", "rsc", "krc",
    "u17", "u18", "u19", "u20", "u21", "u23",
    "ii", "b-team", "b",
}

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
        f"Browser/JS={'ON' if PLAYWRIGHT_AVAILABLE else 'OFF'} | "
        f"Scanner={'ON' if SCANNER_RUNNING else 'OFF'}"
    )


@app.route("/version")
def version():
    return {
        "version": APP_VERSION,
        "browser_js": PLAYWRIGHT_AVAILABLE,
        "scanner_running": SCANNER_RUNNING,
        "scan_seconds": SCAN_SECONDS,
        "max_browser_workers": MAX_BROWSER_WORKERS,
    }


@app.route("/health")
def health():
    return {
        "ok": True,
        "version": APP_VERSION,
        "browser_js": PLAYWRIGHT_AVAILABLE,
        "scanner_running": SCANNER_RUNNING,
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
# TEXT / TEAM NORMALIZATION
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
    value = clean_text(value).lower()

    if not value:
        return ""

    value = value.replace("&", " and ")
    value = NON_ALNUM.sub(" ", value)
    tokens = value.split()

    # Remove only known football prefixes/suffixes.
    filtered = []
    for token in tokens:
        if token in TEAM_STOPWORDS:
            continue
        filtered.append(token)

    # Remove immediate duplicated sequences such as:
    # "como como" -> "como"
    if len(filtered) >= 2 and len(filtered) % 2 == 0:
        half = len(filtered) // 2
        if filtered[:half] == filtered[half:]:
            filtered = filtered[:half]

    collapsed = []
    for token in filtered:
        if not collapsed or token != collapsed[-1]:
            collapsed.append(token)

    return " ".join(collapsed)


def display_team(value):
    return clean_text(value)


def team_tokens(value):
    return set(normalize_team(value).split())


def meaningful_tokens(value):
    return {
        token
        for token in team_tokens(value)
        if len(token) >= 2
    }


def token_match_ratio(source, text):
    source_tokens = meaningful_tokens(source)
    text_norm = normalize_team(text)

    if not source_tokens or not text_norm:
        return 0.0

    hits = sum(
        1 for token in source_tokens
        if token in text_norm.split()
    )

    return hits / len(source_tokens)


def team_match_score(source_name, bookmaker_text):
    source = normalize_team(source_name)
    text = normalize_team(bookmaker_text)

    if not source or not text:
        return 0.0

    if source == text:
        return 1.0

    if len(source) >= 5 and source in text:
        return 0.95

    ratio = token_match_ratio(source_name, bookmaker_text)
    tokens = meaningful_tokens(source_name)

    if len(tokens) >= 3:
        if ratio >= 0.85:
            return 0.92
        if ratio >= 0.70:
            return 0.80
        if ratio >= 0.55:
            return 0.65
    else:
        if ratio == 1.0:
            return 0.86

    return 0.0


def pair_match_score(home, away, bookmaker_text):
    home_score = team_match_score(home, bookmaker_text)
    away_score = team_match_score(away, bookmaker_text)
    return min(home_score, away_score)


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN:
        print("[TELEGRAM] Missing TELEGRAM_BOT_TOKEN", flush=True)
        return False

    if not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] Missing TELEGRAM_CHAT_ID", flush=True)
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
            print("[TELEGRAM] Sent", flush=True)
            return True

        print(
            f"[TELEGRAM] HTTP {response.status_code}: "
            f"{response.text[:300]}",
            flush=True,
        )

    except Exception as exc:
        print(f"[TELEGRAM] ERROR: {exc}", flush=True)

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
                f"URL={response.url} | "
                f"HTML={len(response.text)}",
                flush=True,
            )

            if response.ok and len(response.text) > 50000:
                return response.text

        except Exception as exc:
            print(f"[KOOORA] ERROR {url}: {exc}", flush=True)

    return ""


def extract_score_from_text(text):
    text = clean_text(text)

    patterns = [
        r"(?<!\d)(\d{1,2})\s*[-:]\s*(\d{1,2})(?!\d)",
        r"(?<!\d)(\d{1,2})\s+(\d{1,2})(?!\d)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
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
            result.append(display_team(value))

    return result


def extract_team_names_from_card(card, score):
    full = clean_text(card.get_text(" ", strip=True))

    score_texts = [
        f"{score[0]} - {score[1]}",
        f"{score[0]}:{score[1]}",
        f"{score[0]} {score[1]}",
    ]

    before = ""
    after = ""

    for score_text in score_texts:
        pos = full.find(score_text)
        if pos >= 0:
            before = full[:pos]
            after = full[pos + len(score_text):]
            break

    if not before or not after:
        return "", ""

    def candidates(part):
        part = clean_text(part)

        part = re.sub(
            r"(?:FT|HT|LIVE|RESULT|FIXTURE|HALF\s*TIME|"
            r"FULL\s*TIME|الشوط\s*الأول|نهاية\s*المباراة|انتهت).*?$",
            "",
            part,
            flags=re.I,
        )

        part = re.sub(r"\b\d{1,2}\b", " ", part)
        part = clean_text(part)

        raw = [part]
        raw.extend(
            re.split(
                r"\s{2,}|\s+\|\s+|\s+•\s+|[|/]",
                part,
            )
        )

        return unique_strings(raw)

    left_candidates = [
        x for x in candidates(before)
        if 1 <= len(normalize_team(x).split()) <= 8
    ]

    right_candidates = [
        x for x in candidates(after)
        if 1 <= len(normalize_team(x).split()) <= 8
    ]

    if not left_candidates or not right_candidates:
        return "", ""

    left = min(
        left_candidates,
        key=lambda x: len(normalize_team(x).split()),
    )
    right = min(
        right_candidates,
        key=lambda x: len(normalize_team(x).split()),
    )

    return left, right


def parse_kooora(html):
    soup = BeautifulSoup(html, "html.parser")

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
            card.get("data-match-status", "")
        ).upper()

        if status not in counts:
            continue

        counts[status] += 1

        score = extract_score_from_text(
            card.get_text(" ", strip=True)
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
                status_element.get_text(" ", strip=True)
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
            card, score
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

    result = list(unique.values())

    print(
        f"[KOOORA] cards={len(cards)} | "
        f"FIXTURE={counts['FIXTURE']} | "
        f"LIVE={counts['LIVE']} | "
        f"RESULT={counts['RESULT']} | "
        f"HT/FT={len(result)}",
        flush=True,
    )

    for match in result[:60]:
        print(
            f"[KOOORA] {match['phase']} "
            f"{match['home']} "
            f"{match['home_score']}-"
            f"{match['away_score']} "
            f"{match['away']}",
            flush=True,
        )

    return result


# ============================================================
# PAGE HELPERS
# ============================================================

def page_contains_marker(text, markers):
    low = clean_text(text).lower()
    return any(marker.lower() in low for marker in markers)


def is_protected_page(text, final_url=""):
    return page_contains_marker(
        f"{text} {final_url}",
        CAPTCHA_MARKERS,
    )


def classify_page(text, final_url=""):
    combined = f"{text} {final_url}"

    if is_protected_page(combined, final_url):
        return "CAPTCHA"

    if page_contains_marker(combined, LIVE_MARKERS):
        return "LIVE"

    if page_contains_marker(combined, PREMATCH_MARKERS):
        return "PREMATCH"

    if page_contains_marker(combined, POSTMATCH_MARKERS):
        return "POSTMATCH"

    return "NOT_CONFIRMED"


def absolute_url(base_url, href):
    if not href:
        return ""

    try:
        return urljoin(base_url, href)
    except Exception:
        return ""


def same_domain(url_a, url_b):
    try:
        host_a = urlparse(url_a).netloc.lower()
        host_b = urlparse(url_b).netloc.lower()

        if host_a.startswith("www."):
            host_a = host_a[4:]

        if host_b.startswith("www."):
            host_b = host_b[4:]

        return host_a == host_b
    except Exception:
        return False


def relevant_link(url, anchor_text=""):
    combined = f"{url} {anchor_text}".lower()
    return any(hint in combined for hint in EVENT_URL_HINTS)


def link_priority(url, anchor_text="", matches=None):
    score = 0
    combined = f"{url} {anchor_text}".lower()

    if any(hint in combined for hint in SEARCH_URL_HINTS):
        score += 10

    if any(hint in combined for hint in EVENT_URL_HINTS):
        score += 5

    if matches:
        for match in matches:
            for token in (
                meaningful_tokens(match["home"])
                | meaningful_tokens(match["away"])
            ):
                if token.lower() in combined:
                    score += 12

    return score


# ============================================================
# MATCH-LOCAL CONFIRMATION
# ============================================================

def event_windows(text, match, window=900):
    """
    Return text windows where both teams occur reasonably close
    together. This prevents a league page containing both teams
    somewhere far apart from being treated as one exact event.
    """
    clean = clean_text(text)
    low = clean.lower()

    home_tokens = meaningful_tokens(match["home"])
    away_tokens = meaningful_tokens(match["away"])

    if not home_tokens or not away_tokens:
        return []

    positions = []

    for token in home_tokens:
        start = 0
        needle = token.lower()

        while True:
            pos = low.find(needle, start)
            if pos < 0:
                break
            positions.append(pos)
            start = pos + max(1, len(needle))

    windows = []

    for pos in positions[:100]:
        left = max(0, pos - window)
        right = min(len(clean), pos + window)
        block = clean[left:right]
        block_low = block.lower()

        if all(token.lower() in block_low for token in away_tokens):
            windows.append(block)

    return windows


def strong_pair_match(text, match):
    windows = event_windows(text, match, 1000)

    if not windows:
        return 0.0

    best = 0.0

    for block in windows:
        score = pair_match_score(
            match["home"],
            match["away"],
            block,
        )
        best = max(best, score)

    return best


def local_prematch_confirmation(text, match):
    windows = event_windows(text, match, 1000)

    if not windows:
        return False

    for block in windows:
        low = block.lower()

        if page_contains_marker(
            block,
            POSTMATCH_MARKERS,
        ):
            continue

        if page_contains_marker(
            block,
            LIVE_MARKERS,
        ):
            continue

        # Strongest signal: explicit pre-match wording.
        if page_contains_marker(
            block,
            PREMATCH_MARKERS,
        ):
            return True

        # Time close to both team names can be enough when there
        # is no live/final marker. Require a normal clock format.
        if re.search(
            r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b",
            low,
        ):
            return True

    return False


# ============================================================
# CANDIDATE LINK DISCOVERY
# ============================================================

def collect_candidate_links(page, base_url, matches):
    candidates = []

    try:
        anchors = page.locator("a")
        count = min(anchors.count(), 1200)

        for index in range(count):
            try:
                element = anchors.nth(index)

                href = element.get_attribute("href")
                if not href:
                    continue

                url = absolute_url(base_url, href)

                if not url:
                    continue

                if not same_domain(base_url, url):
                    continue

                if url.startswith(("javascript:", "mailto:", "#")):
                    continue

                text = clean_text(
                    element.inner_text(timeout=800)
                )

                if not relevant_link(url, text):
                    continue

                priority = link_priority(
                    url, text, matches
                )

                candidates.append(
                    (priority, url, text)
                )

            except Exception:
                continue

    except Exception as exc:
        print(
            f"[DISCOVERY] ERROR: {exc}",
            flush=True,
        )

    unique = {}

    for priority, url, text in candidates:
        old = unique.get(url)
        if old is None or priority > old[0]:
            unique[url] = (priority, url, text)

    ordered = sorted(
        unique.values(),
        key=lambda x: x[0],
        reverse=True,
    )

    return ordered[:MAX_EVENT_LINKS]


# ============================================================
# SPORT-PAGE EXPANSION
# ============================================================

def expand_from_sport_pages(
    page,
    base_url,
    matches,
    initial_candidates,
):
    all_candidates = list(initial_candidates)
    visited = set()

    sport_candidates = [
        item for item in initial_candidates
        if any(
            hint in f"{item[1]} {item[2]}".lower()
            for hint in (
                "sport", "sports", "football", "soccer",
                "fussball", "spiel", "spiele", "live",
                "wetten", "prematch",
            )
        )
    ]

    for _, url, _ in sport_candidates[:MAX_SPORT_PAGES]:
        if url in visited:
            continue

        visited.add(url)

        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=EVENT_SEARCH_TIMEOUT_MS,
            )
            page.wait_for_timeout(800)

            if is_protected_page(
                page.locator("body").inner_text(timeout=3000),
                page.url,
            ):
                continue

            discovered = collect_candidate_links(
                page,
                page.url,
                matches,
            )

            all_candidates.extend(discovered)

        except Exception as exc:
            print(
                f"[SPORT] ERROR {url}: {exc}",
                flush=True,
            )

    unique = {}

    for priority, url, text in all_candidates:
        old = unique.get(url)
        if old is None or priority > old[0]:
            unique[url] = (priority, url, text)

    ordered = sorted(
        unique.values(),
        key=lambda x: x[0],
        reverse=True,
    )

    return ordered[:MAX_EVENT_LINKS]


# ============================================================
# EVENT PAGE INSPECTION
# ============================================================

def inspect_event_links(
    page,
    matches,
    candidates,
):
    confirmed = []
    visited = set()

    for _, url, _ in candidates:
        if url in visited:
            continue

        visited.add(url)

        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=EVENT_SEARCH_TIMEOUT_MS,
            )
            page.wait_for_timeout(EVENT_PAGE_WAIT_MS)

            final_url = page.url
            title = page.title()

            text = page.locator(
                "body"
            ).inner_text(timeout=5000)

            combined = f"{title} {text}"

            if is_protected_page(combined, final_url):
                print(
                    f"[EVENT] PROTECTED {final_url}",
                    flush=True,
                )
                continue

            for match in matches:
                confidence = strong_pair_match(
                    text, match
                )

                if confidence < 0.80:
                    continue

                if local_prematch_confirmation(
                    text, match
                ):
                    print(
                        f"[MATCH] {match['home']} vs "
                        f"{match['away']} | "
                        f"confidence={confidence:.2f} | "
                        f"PREMATCH | {final_url}",
                        flush=True,
                    )

                    confirmed.append(
                        {
                            "match": match,
                            "confidence": confidence,
                            "status": "PREMATCH",
                            "url": final_url,
                        }
                    )

        except PlaywrightTimeoutError:
            print(
                f"[EVENT] TIMEOUT {url}",
                flush=True,
            )

        except Exception as exc:
            print(
                f"[EVENT] ERROR {url}: {exc}",
                flush=True,
            )

    return confirmed


# ============================================================
# SEARCH CONTROLS
# ============================================================

def find_search_controls(page):
    selectors = [
        "input[type='search']",
        "input[name*='search' i]",
        "input[placeholder*='search' i]",
        "input[placeholder*='suche' i]",
        "input[placeholder*='suchen' i]",
        "input[placeholder*='finden' i]",
    ]

    found = []

    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = min(locator.count(), 8)

            for i in range(count):
                element = locator.nth(i)

                try:
                    if element.is_visible():
                        found.append(element)
                except Exception:
                    pass

            if found:
                return found

        except Exception:
            continue

    return []


def search_event_in_page(page, match):
    controls = find_search_controls(page)

    if not controls:
        return []

    search_terms = [
        f"{match['home']} {match['away']}",
        match["home"],
        match["away"],
    ]

    discovered = []

    for term in search_terms:
        if not term:
            continue

        for control in controls[:3]:
            try:
                control.fill(term, timeout=2000)
                control.press("Enter", timeout=2000)
                page.wait_for_timeout(EVENT_PAGE_WAIT_MS)

                body_text = page.locator(
                    "body"
                ).inner_text(timeout=4000)

                if is_protected_page(body_text, page.url):
                    return []

                confidence = strong_pair_match(
                    body_text, match
                )

                if confidence >= 0.80:
                    discovered.append(
                        {
                            "url": page.url,
                            "text": body_text,
                            "confidence": confidence,
                        }
                    )

                # Also collect result/event links.
                links = collect_candidate_links(
                    page,
                    page.url,
                    [match],
                )

                for priority, url, text in links:
                    discovered.append(
                        {
                            "url": url,
                            "text": text,
                            "confidence": priority / 100.0,
                        }
                    )

                if discovered:
                    return discovered

            except Exception:
                continue

    return discovered


# ============================================================
# BROWSER SCANNER
# ============================================================

def browser_check_one(bookmaker, url, matches):
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

            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=BROWSER_TIMEOUT_MS,
            )

            page.wait_for_timeout(BROWSER_WAIT_MS)

            final_url = page.url
            title = page.title()

            text = page.locator(
                "body"
            ).inner_text(timeout=5000)

            http_status = response.status if response else 0

            print(
                f"[BROWSER] {bookmaker} "
                f"HTTP={http_status} "
                f"URL={final_url} "
                f"TEXT={len(text)}",
                flush=True,
            )

            if is_protected_page(
                f"{title} {text}",
                final_url,
            ):
                print(
                    f"[BROWSER] {bookmaker} "
                    "CAPTCHA/PROTECTION",
                    flush=True,
                )
                return {
                    "bookmaker": bookmaker,
                    "status": "CAPTCHA",
                    "final_url": final_url,
                    "matches": [],
                }

            # ------------------------------------------------
            # 1. Fast homepage/event-local check
            # ------------------------------------------------

            found = []

            for match in matches:
                confidence = strong_pair_match(
                    text, match
                )

                if confidence < 0.80:
                    continue

                if local_prematch_confirmation(
                    text, match
                ):
                    found.append(
                        {
                            "match": match,
                            "confidence": confidence,
                            "status": "PREMATCH",
                            "url": final_url,
                        }
                    )

            if found:
                print(
                    f"[BROWSER] {bookmaker} "
                    f"PREMATCH homepage found={len(found)}",
                    flush=True,
                )
                return {
                    "bookmaker": bookmaker,
                    "status": "PREMATCH",
                    "final_url": final_url,
                    "matches": found,
                }

            # ------------------------------------------------
            # 2. Discover event/sport links
            # ------------------------------------------------

            candidates = collect_candidate_links(
                page,
                final_url,
                matches,
            )

            print(
                f"[DISCOVERY] {bookmaker} "
                f"initial_links={len(candidates)}",
                flush=True,
            )

            candidates = expand_from_sport_pages(
                page,
                final_url,
                matches,
                candidates,
            )

            print(
                f"[DISCOVERY] {bookmaker} "
                f"expanded_links={len(candidates)}",
                flush=True,
            )

            # ------------------------------------------------
            # 3. Inspect event pages
            # ------------------------------------------------

            confirmed = inspect_event_links(
                page,
                matches,
                candidates,
            )

            if confirmed:
                return {
                    "bookmaker": bookmaker,
                    "status": "PREMATCH",
                    "final_url": page.url,
                    "matches": confirmed,
                }

            # ------------------------------------------------
            # 4. Search form fallback
            # ------------------------------------------------

            search_results = []

            for match in matches[:MAX_SEARCH_MATCHES]:
                try:
                    page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=BROWSER_TIMEOUT_MS,
                    )
                    page.wait_for_timeout(900)

                    home_text = page.locator(
                        "body"
                    ).inner_text(timeout=3000)

                    if is_protected_page(
                        home_text,
                        page.url,
                    ):
                        break

                    results = search_event_in_page(
                        page,
                        match,
                    )

                    for item in results:
                        if item.get("text"):
                            confidence = strong_pair_match(
                                item["text"],
                                match,
                            )

                            if (
                                confidence >= 0.80
                                and local_prematch_confirmation(
                                    item["text"],
                                    match,
                                )
                            ):
                                search_results.append(
                                    {
                                        "match": match,
                                        "confidence": confidence,
                                        "status": "PREMATCH",
                                        "url": item["url"],
                                    }
                                )

                        else:
                            # Event URL discovered by search:
                            try:
                                page.goto(
                                    item["url"],
                                    wait_until="domcontentloaded",
                                    timeout=EVENT_SEARCH_TIMEOUT_MS,
                                )
                                page.wait_for_timeout(
                                    EVENT_PAGE_WAIT_MS
                                )

                                event_text = page.locator(
                                    "body"
                                ).inner_text(timeout=4000)

                                confidence = strong_pair_match(
                                    event_text,
                                    match,
                                )

                                if (
                                    confidence >= 0.80
                                    and local_prematch_confirmation(
                                        event_text,
                                        match,
                                    )
                                ):
                                    search_results.append(
                                        {
                                            "match": match,
                                            "confidence": confidence,
                                            "status": "PREMATCH",
                                            "url": page.url,
                                        }
                                    )

                            except Exception:
                                continue

                except Exception as exc:
                    print(
                        f"[SEARCH] {bookmaker} "
                        f"ERROR: {exc}",
                        flush=True,
                    )

            if search_results:
                return {
                    "bookmaker": bookmaker,
                    "status": "PREMATCH",
                    "final_url": page.url,
                    "matches": search_results,
                }

            status = classify_page(
                text,
                final_url,
            )

            print(
                f"[BROWSER] {bookmaker} "
                f"{status} final={final_url}",
                flush=True,
            )

            return {
                "bookmaker": bookmaker,
                "status": status,
                "final_url": final_url,
                "matches": [],
            }

    except PlaywrightTimeoutError as exc:
        print(
            f"[BROWSER] {bookmaker} TIMEOUT: {exc}",
            flush=True,
        )
        return {
            "bookmaker": bookmaker,
            "status": "TIMEOUT",
            "final_url": url,
            "matches": [],
        }

    except Exception as exc:
        print(
            f"[BROWSER] {bookmaker} ERROR: {exc}",
            flush=True,
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

def requests_check_one(bookmaker, url, matches):
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

        text = soup.get_text(" ", strip=True)

        if is_protected_page(text, final_url):
            status = "CAPTCHA"
        else:
            status = classify_page(text, final_url)

        found = []

        if status == "PREMATCH":
            for match in matches:
                confidence = strong_pair_match(
                    text, match
                )

                if confidence >= 0.80 and local_prematch_confirmation(
                    text, match
                ):
                    found.append(
                        {
                            "match": match,
                            "confidence": confidence,
                            "status": "PREMATCH",
                            "url": final_url,
                        }
                    )

        print(
            f"[HTTP] {bookmaker} "
            f"HTTP={response.status_code} "
            f"{status} found={len(found)}",
            flush=True,
        )

        return {
            "bookmaker": bookmaker,
            "status": status,
            "final_url": final_url,
            "matches": found,
        }

    except Exception as exc:
        print(
            f"[HTTP] {bookmaker} ERROR: {exc}",
            flush=True,
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

    workers = max(1, MAX_BROWSER_WORKERS)

    print(
        f"[BOOKMAKER] Starting scan: "
        f"{len(BOOKMAKERS)} sites | workers={workers}",
        flush=True,
    )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                worker,
                bookmaker,
                url,
                matches,
            )
            for bookmaker, url in BOOKMAKERS
        ]

        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                print(
                    f"[BOOKMAKER] worker error: {exc}",
                    flush=True,
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


def send_same_match_alert(bookmaker_result, found):
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

    if telegram_send(message):
        sent_alerts.add(key)


# ============================================================
# SCAN PROCESS
# ============================================================

def process_scan():
    started = time.time()

    print(
        "[SCAN] Cycle started",
        flush=True,
    )

    html = fetch_kooora_html()

    if not html:
        print(
            "[SCAN] Kooora unavailable",
            flush=True,
        )
        return

    matches = parse_kooora(html)

    if not matches:
        print(
            "[SCAN] No HT/FT matches extracted",
            flush=True,
        )
        return

    print(
        f"[SCAN] Checking {len(matches)} Kooora HT/FT "
        f"matches against {len(BOOKMAKERS)} bookmakers | "
        f"Browser/JS={'ON' if PLAYWRIGHT_AVAILABLE else 'OFF'}",
        flush=True,
    )

    results = scan_bookmakers(matches)

    confirmed = 0
    status_counts = {}

    for result in results:
        status = result.get("status", "UNKNOWN")

        status_counts[status] = (
            status_counts.get(status, 0) + 1
        )

        for found in result.get("matches", []):
            if found.get("status") != "PREMATCH":
                continue

            confirmed += 1
            send_same_match_alert(result, found)

    elapsed = time.time() - started

    print(
        f"[SCAN] Done in {elapsed:.1f}s | "
        f"bookmaker statuses={status_counts} | "
        f"confirmed={confirmed}",
        flush=True,
    )


# ============================================================
# SCANNER LOOP
# ============================================================

def scanner_loop():
    global SCANNER_RUNNING

    SCANNER_RUNNING = True

    print(
        f"[START] {APP_VERSION} | "
        f"Kooora Match Tracker | "
        f"interval={SCAN_SECONDS}s | "
        f"Playwright="
        f"{'AVAILABLE' if PLAYWRIGHT_AVAILABLE else 'NOT INSTALLED'}",
        flush=True,
    )

    print(
        "[SCANNER] Thread started",
        flush=True,
    )

    if not TELEGRAM_BOT_TOKEN:
        print(
            "[START] WARNING: TELEGRAM_BOT_TOKEN is missing",
            flush=True,
        )

    if not TELEGRAM_CHAT_ID:
        print(
            "[START] WARNING: TELEGRAM_CHAT_ID is missing",
            flush=True,
        )

    while True:
        cycle_started = time.monotonic()

        try:
            process_scan()
        except Exception as exc:
            print(
                f"[SCAN] UNHANDLED ERROR: {exc}",
                flush=True,
            )

        elapsed = time.monotonic() - cycle_started
        sleep_for = max(
            1,
            SCAN_SECONDS - elapsed,
        )

        print(
            f"[SCANNER] Next scan in {sleep_for:.1f}s",
            flush=True,
        )

        time.sleep(sleep_for)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))

    print(
        "[MAIN] Starting Flask + scanner",
        flush=True,
    )

    thread = threading.Thread(
        target=scanner_loop,
        daemon=True,
        name="kooora-scanner",
    )

    thread.start()

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )
'''

path = Path("/mnt/data/main_v3_1.py")
path.write_text(code, encoding="utf-8")

# Syntax validation
compile(code, str(path), "exec")

print(f"Created: {path}")
print(f"Size: {path.stat().st_size:,} bytes")
print("Syntax check: OK")
