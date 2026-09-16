import os
import re
import time
import threading
import unicodedata
from datetime import datetime

import traceback
from urllib.parse import urljoin, urlparse, quote
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from flask import Flask

try:
    from playwright.sync_api import (
        sync_playwright,
        TimeoutError as PlaywrightTimeoutError,
    )
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False


# ============================================================
# KOOORA MATCH TRACKER
# VERSION 3.3
#
# Main rule:
#     DOUBT = REJECT
#
# A bookmaker alert is sent only when:
# 1. The same HOME + AWAY teams are found.
# 2. Both teams are inside the SAME local event window.
# 3. Match confidence is >= 0.92.
# 4. One-word team names require exact local matching and 0.93.
# 5. The local event window contains NO LIVE / HT / FT signal.
# 6. The local event window contains a PREMATCH/scheduled signal.
# 7. Telegram confirms successful delivery before sent_alerts is updated.
#
# CAPTCHA / Cloudflare / anti-bot:
#     NEVER bypassed.
#     Protected bookmaker is skipped.
# ============================================================


def log(message):
    """Immediate Render-friendly logging."""
    print(message, flush=True)


# Live scanner diagnostics. Never contains Telegram secrets.
scanner_state_lock = threading.Lock()
scanner_state = {
    "active": False,
    "phase": "IDLE",
    "scan_started_at": None,
    "last_scan_started_at": None,
    "last_scan_finished_at": None,
    "last_successful_scan_at": None,
    "last_scan_duration_seconds": None,
    "last_error": None,
    "last_kooora_matches": 0,
    "last_bookmaker_results": 0,
}


def update_scanner_state(**updates):
    with scanner_state_lock:
        scanner_state.update(updates)


def get_scanner_state():
    with scanner_state_lock:
        return dict(scanner_state)


# ============================================================
# CONFIG
# ============================================================

APP_VERSION = "KOOORA_BROWSER_V3_3"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

KOOORA_URL = "https://www.kooora.com/كرة القدم/مباريات-اليوم"
KOOORA_FALLBACK_URL = "https://www.kooora.com/default.aspx?g=matches"

SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "60"))

BROWSER_TIMEOUT_MS = int(
    os.getenv("BROWSER_TIMEOUT_MS", "20000")
)

BROWSER_WAIT_MS = int(
    os.getenv("BROWSER_WAIT_MS", "5000")
)

MAX_BROWSER_WORKERS = int(
    os.getenv("MAX_BROWSER_WORKERS", "3")
)

MIN_MATCH_CONFIDENCE = float(
    os.getenv("MIN_MATCH_CONFIDENCE", "0.92")
)

ONE_WORD_EXACT_CONFIDENCE = 0.93

# Maximum character distance used by the strict text fallback.
EVENT_WINDOW_CHARS = int(
    os.getenv("EVENT_WINDOW_CHARS", "900")
)

# Maximum number of candidate DOM event blocks inspected.
MAX_EVENT_BLOCKS = int(
    os.getenv("MAX_EVENT_BLOCKS", "500")
)

HTTP_TIMEOUT = int(
    os.getenv("HTTP_TIMEOUT", "20")
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
    "sicherheitsprüfung",
]

LIVE_MARKERS = [
    "live",
    "livewetten",
    "live betting",
    "in-play",
    "in play",
    "spiel läuft",
    "spiel läuft!",
    "läuft",
    "livewetten",
    "canli",
    "مباشر",
    "حي",
]

HT_MARKERS = [
    "ht",
    "half time",
    "halftime",
    "half-time",
    "halbzeit",
    "pause",
    "ht.",
    "الشوط الأول",
    "بين الشوطين",
]

POSTMATCH_MARKERS = [
    "ft",
    "full time",
    "full-time",
    "finished",
    "finish",
    "final",
    "ended",
    "completed",
    "match ended",
    "spiel beendet",
    "beendet",
    "endstand",
    "abpfiff",
    "ergebnis",
    "result",
    "ergebnisse",
    "النهاية",
    "انتهت",
    "النتيجة",
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
    "starting in",
    "kickoff",
    "kick-off",
    "vor dem spiel",
    "noch nicht begonnen",
    "noch nicht gestartet",
    "bevorstehend",
    "angesetzt",
    "geplant",
    "قبل المباراة",
    "لم تبدأ",
    "لم تبدأ بعد",
    "موعد المباراة",
]


# Generic terms that are not useful for identifying a team.
TEAM_STOPWORDS = {
    "fc",
    "cf",
    "sc",
    "ac",
    "fk",
    "sk",
    "sv",
    "vfb",
    "tsv",
    "afc",
    "bsc",
    "ssc",
    "us",
    "as",
    "rc",
    "cd",
    "ud",
    "ca",
    "u19",
    "u20",
    "u21",
    "u23",
    "ii",
    "iii",
}


# ============================================================
# GLOBAL STATE
# ============================================================

sent_alerts = set()

sent_alerts_lock = threading.Lock()

scan_lock = threading.Lock()


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return (
        f"{APP_VERSION} is running and monitoring "
        f"Kooora HT/FT matches."
    )


@app.route("/health")
def health():
    state = get_scanner_state()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "playwright": PLAYWRIGHT_AVAILABLE,
        "scan_seconds": SCAN_SECONDS,
        "workers": MAX_BROWSER_WORKERS,
        "min_match_confidence": MIN_MATCH_CONFIDENCE,
        "scanner": state,
    }


@app.route("/version")
def version():
    return {
        "version": APP_VERSION,
        "playwright_available": PLAYWRIGHT_AVAILABLE,
    }


# ============================================================
# GENERAL TEXT HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    value = str(value)

    value = unicodedata.normalize(
        "NFKC",
        value,
    )

    value = value.replace("\u200f", " ")
    value = value.replace("\u200e", " ")
    value = value.replace("\xa0", " ")

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def normalize_for_search(value):
    value = clean_text(value).lower()

    # Normalize punctuation into spaces.
    value = re.sub(
        r"[\u2010-\u2015\-_/|:;,(){}\[\].]+",
        " ",
        value,
    )

    # Remove score patterns.
    value = re.sub(
        r"\b\d{1,2}\s*[-:]\s*\d{1,2}\b",
        " ",
        value,
    )

    # Remove obvious state markers.
    value = re.sub(
        r"\b(?:ft|ht|live|result|fixture)\b",
        " ",
        value,
        flags=re.I,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def normalize_team(value):
    value = normalize_for_search(value)

    tokens = re.findall(
        r"[a-z0-9\u0600-\u06ff]+",
        value,
        flags=re.I,
    )

    if not tokens:
        return ""

    # Collapse exact adjacent duplicate tokens.
    collapsed = []

    for token in tokens:
        if not collapsed or token != collapsed[-1]:
            collapsed.append(token)

    # Collapse exact A B A B duplication.
    if len(collapsed) >= 4 and len(collapsed) % 2 == 0:
        half = len(collapsed) // 2

        if collapsed[:half] == collapsed[half:]:
            collapsed = collapsed[:half]

    return " ".join(collapsed)


def meaningful_tokens(value):
    tokens = normalize_team(value).split()

    result = []

    for token in tokens:
        if token in TEAM_STOPWORDS:
            continue

        if len(token) < 3:
            continue

        result.append(token)

    return result


def normalized_word_list(value):
    return normalize_team(value).split()


def is_one_meaningful_word(value):
    return len(meaningful_tokens(value)) == 1


# ============================================================
# TEAM MATCHING
# ============================================================

def team_exact_in_text(team, text):
    """
    Strict exact local matching.

    This is intentionally stricter than substring matching.
    """

    team_norm = normalize_team(team)
    text_norm = normalize_team(text)

    if not team_norm or not text_norm:
        return False

    if team_norm == text_norm:
        return True

    team_tokens = meaningful_tokens(team)

    if not team_tokens:
        return False

    text_tokens = set(
        meaningful_tokens(text)
    )

    # For a one-word team, exact token match only.
    if len(team_tokens) == 1:
        return team_tokens[0] in text_tokens

    # For multi-word team, ALL meaningful tokens must exist.
    return all(
        token in text_tokens
        for token in team_tokens
    )


def team_match_score(team, local_text):
    """
    Conservative score.

    1.00 = exact normalized equality
    0.95 = exact multi-word phrase in local block
    0.93 = exact one-word team token
    0.00 = not confirmed

    There is deliberately NO 0.80 / 0.82 / 0.90 partial score.
    """

    team_norm = normalize_team(team)
    local_norm = normalize_team(local_text)

    if not team_norm or not local_norm:
        return 0.0

    # Exact complete local text.
    if team_norm == local_norm:
        return 1.0

    tokens = meaningful_tokens(team)

    if not tokens:
        return 0.0

    local_tokens = set(
        meaningful_tokens(local_text)
    )

    # One-word team:
    # only exact token match is accepted.
    if len(tokens) == 1:
        if tokens[0] in local_tokens:
            return ONE_WORD_EXACT_CONFIDENCE

        return 0.0

    # Multi-word exact normalized phrase.
    if team_norm in local_norm:
        return 0.95

    # All meaningful words must exist.
    if all(
        token in local_tokens
        for token in tokens
    ):
        return 0.93

    return 0.0


def pair_match_score(home, away, local_text):
    """
    Both teams must be confirmed inside the SAME local text.
    """

    home_score = team_match_score(
        home,
        local_text,
    )

    away_score = team_match_score(
        away,
        local_text,
    )

    if (
        home_score < MIN_MATCH_CONFIDENCE
        or away_score < MIN_MATCH_CONFIDENCE
    ):
        return 0.0

    return min(
        home_score,
        away_score,
    )


# ============================================================
# STATUS HELPERS
# ============================================================

def contains_marker(text, markers):
    low = clean_text(text).lower()

    for marker in markers:
        if marker.lower() in low:
            return True

    return False


def detect_local_status(text):
    """
    IMPORTANT:
    This function is used only on a LOCAL EVENT WINDOW.

    It never decides the target match state from the bookmaker
    page as a whole.
    """

    text = clean_text(text)

    if not text:
        return "UNKNOWN"

    # FT/finished has highest priority.
    if contains_marker(
        text,
        POSTMATCH_MARKERS,
    ):
        return "FT"

    # HT/live means the event is already underway.
    if contains_marker(
        text,
        HT_MARKERS,
    ):
        return "LIVE"

    if contains_marker(
        text,
        LIVE_MARKERS,
    ):
        return "LIVE"

    if contains_marker(
        text,
        PREMATCH_MARKERS,
    ):
        return "PREMATCH"

    # A scheduled time without a live/post marker can be useful,
    # but only after team matching has already succeeded.
    if has_explicit_match_time(text):
        return "SCHEDULED_TIME"

    return "UNKNOWN"


def has_explicit_match_time(text):
    """
    Detect normal football kickoff times such as:
    18:00
    20:30
    21:45
    """

    if not text:
        return False

    return bool(
        re.search(
            r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b",
            text,
        )
    )


# ============================================================
# KOOORA
# ============================================================

def fetch_kooora_html():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar,en;q=0.8",
    }

    urls = [
        KOOORA_URL,
        KOOORA_FALLBACK_URL,
    ]

    for url in urls:
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=HTTP_TIMEOUT,
            )

            log(
                f"[KOOORA] HTTP={response.status_code} "
                f"url={response.url} "
                f"length={len(response.text)}"
            )

            if response.status_code == 200:
                return response.text

        except Exception as exc:
            log(
                f"[KOOORA] ERROR {url}: {exc}"
            )

    return ""


def extract_score(text):
    text = clean_text(text)

    patterns = [
        r"\b(\d{1,2})\s*[-:]\s*(\d{1,2})\b",
        r"\b(\d{1,2})\s*:\s*(\d{1,2})\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
        )

        if match:
            return (
                int(match.group(1)),
                int(match.group(2)),
            )

    return None, None


def extract_team_candidates(card):
    """
    Kooora DOM varies over time, so use several likely selectors.
    """

    selectors = [
        ".fco-team-name",
        ".team-name",
        "[class*='team-name']",
        "[class*='teamName']",
        "[class*='participant']",
        "[class*='competitor']",
        "a",
    ]

    candidates = []

    for selector in selectors:
        try:
            elements = card.select(selector)

            for element in elements:
                value = clean_text(
                    element.get_text(
                        " ",
                        strip=True,
                    )
                )

                if not value:
                    continue

                value = re.sub(
                    r"\b(?:FT|HT|LIVE|FIXTURE|RESULT)\b",
                    " ",
                    value,
                    flags=re.I,
                )

                value = clean_text(value)

                if not value:
                    continue

                # Do not accept score-only strings.
                if re.fullmatch(
                    r"\d{1,2}\s*[-:]\s*\d{1,2}",
                    value,
                ):
                    continue

                norm = normalize_team(value)

                if len(norm) < 2:
                    continue

                if norm not in [
                    normalize_team(x)
                    for x in candidates
                ]:
                    candidates.append(value)

        except Exception:
            continue

    return candidates


def parse_kooora(html):
    if not html:
        return []

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    cards = soup.select(
        ".fco-match-list-item"
    )

    if not cards:
        cards = soup.select(
            "[data-match-status]"
        )

    if not cards:
        log(
            "[KOOORA] No match cards found"
        )
        return []

    matches = []

    counts = {
        "FIXTURE": 0,
        "LIVE": 0,
        "RESULT": 0,
    }

    skip_counts = {
        "NO_SCORE": 0,
        "NO_TEAMS": 0,
        "NO_PHASE": 0,
    }

    for card in cards:
        try:
            status = clean_text(
                card.get(
                    "data-match-status",
                    "",
                )
            ).upper()

            if status in counts:
                counts[status] += 1

            text = clean_text(
                card.get_text(
                    " ",
                    strip=True,
                )
            )

            # Determine the phase BEFORE requiring a score.
            # Kooora may expose a LIVE/HT card whose score is rendered
            # in a separate JS element and is therefore not present in
            # the parsed card text. HT detection must not depend on it.
            phase = ""
            status_text = text.lower()

            if status == "RESULT":
                phase = "FT"
            elif status == "LIVE":
                if (
                    "ht" in status_text
                    or "half time" in status_text
                    or "halftime" in status_text
                    or "half-time" in status_text
                    or "halbzeit" in status_text
                    or "pause" in status_text
                    or "الشوط" in status_text
                    or "بين الشوطين" in status_text
                    or "استراحة" in status_text
                    or "نهاية الشوط الأول" in status_text
                    or "نصف الوقت" in status_text
                ):
                    phase = "HT"
                elif (
                    "انتهت" in status_text
                    or "انتهى" in status_text
                    or "full time" in status_text
                    or "finished" in status_text
                    or "final" in status_text
                ):
                    phase = "FT"

            candidates = extract_team_candidates(card)

            if len(candidates) < 2:
                if status == "LIVE":
                    skip_counts["NO_TEAMS"] += 1
                continue

            # Use the first two credible team candidates.
            home = candidates[0]
            away = candidates[1]

            home_norm = normalize_team(home)
            away_norm = normalize_team(away)

            if not home_norm or not away_norm:
                continue

            home_score, away_score = extract_score(text)

            # Score is required for FT, but NOT for HT. Some Kooora
            # half-time cards expose the score outside the parsed text.
            if phase == "FT" and (
                home_score is None or away_score is None
            ):
                if status == "LIVE":
                    skip_counts["NO_SCORE"] += 1
                continue

            if phase == "HT" and (
                home_score is None or away_score is None
            ):
                home_score = None
                away_score = None

            if phase not in {
                "HT",
                "FT",
            }:
                if status == "LIVE":
                    skip_counts["NO_PHASE"] += 1
                    if skip_counts["NO_PHASE"] <= 5:
                        debug_text = clean_text(status_text)
                        log(
                            f"[KOOORA DEBUG] LIVE no HT phase | "
                            f"text={debug_text[:220]}"
                        )
                continue

            matches.append(
                {
                    "home": home,
                    "away": away,
                    "home_norm": home_norm,
                    "away_norm": away_norm,
                    "home_score": home_score,
                    "away_score": away_score,
                    "phase": phase,
                }
            )

        except Exception as exc:
            log(
                f"[KOOORA] card parse error: {exc}"
            )

    # Deduplicate.
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

    log(
        f"[KOOORA] cards={len(cards)} "
        f"FIXTURE={counts['FIXTURE']} "
        f"LIVE={counts['LIVE']} "
        f"RESULT={counts['RESULT']} "
        f"HT/FT={len(result)}"
    )

    if counts["LIVE"]:
        log(
            f"[KOOORA DEBUG] LIVE skips: "
            f"no_score={skip_counts['NO_SCORE']} "
            f"no_teams={skip_counts['NO_TEAMS']} "
            f"no_phase={skip_counts['NO_PHASE']}"
        )

    for match in result[:60]:
        log(
            f"[KOOORA] {match['phase']} "
            f"{match['home']} "
            f"{match['home_score']}-"
            f"{match['away_score']} "
            f"{match['away']}"
        )

    return result


# ============================================================
# PLAYWRIGHT HELPERS
# ============================================================

def protection_detected(title, text, url):
    combined = clean_text(
        f"{title} {text} {url}"
    )

    return contains_marker(
        combined,
        CAPTCHA_MARKERS,
    )


def safe_body_text(page):
    try:
        return clean_text(
            page.locator(
                "body"
            ).inner_text(
                timeout=5000
            )
        )
    except Exception:
        return ""


def likely_event_selector(selector):
    low = selector.lower()

    keywords = [
        "event",
        "match",
        "fixture",
        "game",
        "sport",
        "participant",
        "competitor",
        "contest",
        "coupon",
        "market",
    ]

    return any(
        keyword in low
        for keyword in keywords
    )


def get_event_blocks(page):
    """
    Extract likely local event blocks from the DOM.

    We intentionally avoid using the entire page as one event.
    """

    script = """
    () => {
        const selectors = [
            '[data-testid*="event"]',
            '[data-testid*="match"]',
            '[data-testid*="fixture"]',
            '[data-testid*="game"]',
            '[class*="event"]',
            '[class*="Event"]',
            '[class*="match"]',
            '[class*="Match"]',
            '[class*="fixture"]',
            '[class*="Fixture"]',
            '[class*="game"]',
            '[class*="Game"]',
            '[class*="participant"]',
            '[class*="competitor"]',
            'article',
            'li'
        ];

        const output = [];
        const seen = new Set();

        for (const selector of selectors) {
            let nodes = [];

            try {
                nodes = Array.from(
                    document.querySelectorAll(selector)
                );
            } catch (_) {
                continue;
            }

            for (const node of nodes) {
                try {
                    const text = (node.innerText || "")
                        .replace(/\\s+/g, " ")
                        .trim();

                    if (!text) continue;

                    if (text.length < 20) continue;
                    if (text.length > 2500) continue;

                    const rect = node.getBoundingClientRect();

                    if (rect.width === 0 || rect.height === 0) {
                        continue;
                    }

                    const links = Array.from(
                        node.querySelectorAll("a[href]")
                    )
                    .map(a => ({
                        href: a.href,
                        text: (a.innerText || "")
                            .replace(/\\s+/g, " ")
                            .trim()
                    }))
                    .filter(x => x.href);

                    const key = text + "|" +
                        (links[0]?.href || "");

                    if (seen.has(key)) continue;

                    seen.add(key);

                    output.push({
                        text: text,
                        href: links[0]?.href || "",
                        selector: selector
                    });

                    if (output.length >= 500) {
                        return output;
                    }

                } catch (_) {
                    continue;
                }
            }
        }

        return output;
    }
    """

    try:
        blocks = page.evaluate(script)

        if not isinstance(blocks, list):
            return []

        return blocks[:MAX_EVENT_BLOCKS]

    except Exception as exc:
        log(
            f"[BROWSER] event block extraction error: {exc}"
        )

        return []


def build_text_windows(page_text):
    """
    Text fallback.

    This is NOT page-wide verification.
    It creates bounded windows from the rendered text.
    """

    if not page_text:
        return []

    lines = [
        clean_text(line)
        for line in page_text.splitlines()
        if clean_text(line)
    ]

    windows = []

    current = ""

    for line in lines:
        if len(current) + len(line) + 1 > 1800:
            if current:
                windows.append(current)

            current = line
        else:
            current = (
                f"{current} {line}".strip()
            )

    if current:
        windows.append(current)

    return windows


def strict_event_window_candidates(
    match,
    event_blocks,
    page_text,
):
    """
    Return only event windows where BOTH teams are present.

    DOM event blocks are preferred.
    Text fallback is bounded and conservative.
    """

    candidates = []

    # --------------------------------------------------------
    # 1. DOM event blocks
    # --------------------------------------------------------

    for block in event_blocks:
        text = clean_text(
            block.get("text", "")
        )

        if not text:
            continue

        score = pair_match_score(
            match["home"],
            match["away"],
            text,
        )

        if score < MIN_MATCH_CONFIDENCE:
            continue

        candidates.append(
            {
                "text": text,
                "href": clean_text(
                    block.get("href", "")
                ),
                "score": score,
                "source": "DOM_EVENT",
            }
        )

    if candidates:
        return candidates

    # --------------------------------------------------------
    # 2. Strict bounded text fallback
    # --------------------------------------------------------

    normalized_page = clean_text(
        page_text
    )

    if not normalized_page:
        return []

    home_norm = normalize_team(
        match["home"]
    )

    away_norm = normalize_team(
        match["away"]
    )

    if not home_norm or not away_norm:
        return []

    home_tokens = meaningful_tokens(
        match["home"]
    )

    away_tokens = meaningful_tokens(
        match["away"]
    )

    if not home_tokens or not away_tokens:
        return []

    text_norm = normalize_team(
        normalized_page
    )

    # Locate token occurrences in the normalized text.
    positions = []

    for token in set(
        home_tokens + away_tokens
    ):
        start = 0

        while True:
            index = text_norm.find(
                token,
                start,
            )

            if index < 0:
                break

            positions.append(
                (index, token)
            )

            start = index + len(token)

    if not positions:
        return []

    home_positions = [
        pos
        for pos, token in positions
        if token in home_tokens
    ]

    away_positions = [
        pos
        for pos, token in positions
        if token in away_tokens
    ]

    for home_pos in home_positions:
        for away_pos in away_positions:
            distance = abs(
                home_pos - away_pos
            )

            if distance > EVENT_WINDOW_CHARS:
                continue

            start = max(
                0,
                min(
                    home_pos,
                    away_pos,
                ) - 350,
            )

            end = min(
                len(text_norm),
                max(
                    home_pos,
                    away_pos,
                ) + 700,
            )

            window = clean_text(
                text_norm[start:end]
            )

            score = pair_match_score(
                match["home"],
                match["away"],
                window,
            )

            if score < MIN_MATCH_CONFIDENCE:
                continue

            candidates.append(
                {
                    "text": window,
                    "href": "",
                    "score": score,
                    "source": "TEXT_WINDOW",
                }
            )

    # Deduplicate windows.
    unique = {}

    for candidate in candidates:
        key = (
            candidate["text"],
            candidate["href"],
        )

        unique[key] = candidate

    return list(unique.values())


# ============================================================
# LINK DISCOVERY
# ============================================================

def same_domain(base_url, target_url):
    try:
        base_host = (
            urlparse(base_url)
            .netloc
            .lower()
            .replace("www.", "")
        )

        target_host = (
            urlparse(target_url)
            .netloc
            .lower()
            .replace("www.", "")
        )

        return (
            base_host
            and target_host
            and base_host == target_host
        )

    except Exception:
        return False


def collect_links(page):
    try:
        links = page.locator(
            "a[href]"
        ).evaluate_all(
            """
            els => els.map(a => ({
                href: a.href,
                text: (a.innerText || "").trim()
            }))
            """
        )

        if not isinstance(links, list):
            return []

        return links

    except Exception:
        return []


def link_looks_sport_or_event(link):
    href = clean_text(
        link.get("href", "")
    ).lower()

    text = clean_text(
        link.get("text", "")
    ).lower()

    combined = f"{href} {text}"

    keywords = [
        "football",
        "soccer",
        "sport",
        "fussball",
        "fußball",
        "match",
        "matches",
        "event",
        "events",
        "fixture",
        "fixtures",
        "game",
        "games",
        "wetten",
        "bet",
        "prematch",
        "pre-match",
        "live",
    ]

    return any(
        keyword in combined
        for keyword in keywords
    )


def link_contains_team(link, match):
    text = clean_text(
        link.get("text", "")
    )

    href = clean_text(
        link.get("href", "")
    )

    combined = (
        f"{text} {href}"
    )

    home_score = team_match_score(
        match["home"],
        combined,
    )

    away_score = team_match_score(
        match["away"],
        combined,
    )

    return (
        home_score >= MIN_MATCH_CONFIDENCE
        or away_score >= MIN_MATCH_CONFIDENCE
    )


def collect_candidate_links(
    page,
    base_url,
    match,
):
    links = collect_links(page)

    candidates = []

    seen = set()

    for link in links:
        href = clean_text(
            link.get("href", "")
        )

        if not href:
            continue

        if href.startswith(
            (
                "javascript:",
                "mailto:",
                "tel:",
                "#",
            )
        ):
            continue

        absolute = urljoin(
            base_url,
            href,
        )

        if not same_domain(
            base_url,
            absolute,
        ):
            continue

        if absolute in seen:
            continue

        if not (
            link_looks_sport_or_event(link)
            or link_contains_team(
                link,
                match,
            )
        ):
            continue

        seen.add(absolute)

        candidates.append(absolute)

    return candidates[:120]


# ============================================================
# INTERNAL SEARCH
# ============================================================

def find_search_inputs(page):
    selectors = [
        "input[type='search']",
        "input[placeholder*='Search']",
        "input[placeholder*='search']",
        "input[placeholder*='Suche']",
        "input[placeholder*='suchen']",
        "input[aria-label*='Search']",
        "input[aria-label*='search']",
        "input[aria-label*='Suche']",
        "input[name*='search']",
        "input[id*='search']",
    ]

    result = []

    for selector in selectors:
        try:
            locator = page.locator(
                selector
            )

            count = locator.count()

            for index in range(
                min(count, 5)
            ):
                result.append(
                    locator.nth(index)
                )

        except Exception:
            continue

    return result


def internal_search(
    page,
    bookmaker,
    match,
):
    """
    Try normal visible-site search controls.

    No API reverse engineering.
    No CAPTCHA bypass.
    No anti-bot bypass.
    """

    searches = [
        (
            match["home"],
            match["away"],
        ),
        (
            match["away"],
            match["home"],
        ),
        (
            f"{match['home']} "
            f"{match['away']}",
            "",
        ),
    ]

    for first, second in searches:
        try:
            page.goto(
                page.url,
                wait_until="domcontentloaded",
                timeout=BROWSER_TIMEOUT_MS,
            )

            page.wait_for_timeout(
                min(
                    1500,
                    BROWSER_WAIT_MS,
                )
            )

        except Exception:
            pass

        inputs = find_search_inputs(
            page
        )

        if not inputs:
            continue

        for search_input in inputs[:3]:
            try:
                search_input.fill(
                    ""
                )

                search_input.fill(
                    first
                )

                search_input.press(
                    "Enter"
                )

                page.wait_for_timeout(
                    2500
                )

                title = page.title()

                text = safe_body_text(
                    page
                )

                if protection_detected(
                    title,
                    text,
                    page.url,
                ):
                    log(
                        f"[{bookmaker}] "
                        f"CAPTCHA/protection "
                        f"during internal search"
                    )

                    return {
                        "status": "CAPTCHA",
                        "links": [],
                    }

                links = collect_candidate_links(
                    page,
                    page.url,
                    match,
                )

                if links:
                    return {
                        "status": "SEARCH_FOUND",
                        "links": links,
                    }

            except (
                PlaywrightTimeoutError,
                Exception,
            ):
                continue

    return {
        "status": "SEARCH_NOT_FOUND",
        "links": [],
    }


# ============================================================
# EVENT VERIFICATION
# ============================================================

def verify_event_window(
    match,
    event_window,
):
    """
    The decisive V3.3 verification.

    Required:
        same local event
        both teams
        confidence >= 0.92
        no LIVE
        no HT
        no FT
        explicit PREMATCH or scheduled kickoff time

    Anything else = REJECT.
    """

    text = clean_text(
        event_window.get("text", "")
    )

    if not text:
        return None

    score = pair_match_score(
        match["home"],
        match["away"],
        text,
    )

    if score < MIN_MATCH_CONFIDENCE:
        return None

    # --------------------------------------------------------
    # HARD REJECTION
    # --------------------------------------------------------

    if contains_marker(
        text,
        POSTMATCH_MARKERS,
    ):
        return None

    if contains_marker(
        text,
        HT_MARKERS,
    ):
        return None

    if contains_marker(
        text,
        LIVE_MARKERS,
    ):
        return None

    # --------------------------------------------------------
    # POSITIVE PREMATCH CONFIRMATION
    # --------------------------------------------------------

    has_prematch = contains_marker(
        text,
        PREMATCH_MARKERS,
    )

    has_time = has_explicit_match_time(
        text
    )

    if not has_prematch and not has_time:
        return None

    # If we only have a time, status is scheduled.
    status = (
        "PREMATCH"
        if has_prematch
        else "SCHEDULED_TIME"
    )

    return {
        "status": status,
        "score": score,
        "text": text,
        "href": clean_text(
            event_window.get(
                "href",
                "",
            )
        ),
        "source": event_window.get(
            "source",
            "",
        ),
    }


def verify_page_for_match(
    page,
    match,
    bookmaker,
):
    """
    Verify current rendered page.

    NEVER classify the whole page as PREMATCH.
    """

    title = page.title()

    body_text = safe_body_text(
        page
    )

    if protection_detected(
        title,
        body_text,
        page.url,
    ):
        return {
            "status": "CAPTCHA",
            "matches": [],
        }

    event_blocks = get_event_blocks(
        page
    )

    candidates = strict_event_window_candidates(
        match,
        event_blocks,
        body_text,
    )

    confirmed = []

    for candidate in candidates:
        verification = verify_event_window(
            match,
            candidate,
        )

        if verification is None:
            continue

        verification["match"] = match

        confirmed.append(
            verification
        )

    if confirmed:
        return {
            "status": "CONFIRMED",
            "matches": confirmed,
        }

    return {
        "status": "NOT_CONFIRMED",
        "matches": [],
    }


# ============================================================
# ONE BOOKMAKER
# ============================================================

def browser_check_one(
    bookmaker,
    homepage_url,
    matches,
):
    """
    One Chromium instance per bookmaker.

    Flow:
        Homepage
        -> visible event/sport links
        -> internal search
        -> candidate event
        -> strict local event verification
    """

    if not PLAYWRIGHT_AVAILABLE:
        return {
            "bookmaker": bookmaker,
            "status": "BROWSER_UNAVAILABLE",
            "final_url": homepage_url,
            "matches": [],
        }

    browser = None
    context = None
    page = None
    bookmaker_started = time.monotonic()

    log(f"[{bookmaker}] START | targets={len(matches)}")

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
            # HOMEPAGE
            # ------------------------------------------------

            try:
                response = page.goto(
                    homepage_url,
                    wait_until="domcontentloaded",
                    timeout=BROWSER_TIMEOUT_MS,
                )

                page.wait_for_timeout(
                    BROWSER_WAIT_MS
                )

            except PlaywrightTimeoutError:
                log(
                    f"[{bookmaker}] homepage timeout | elapsed={time.monotonic() - bookmaker_started:.1f}s"
                )

                return {
                    "bookmaker": bookmaker,
                    "status": "TIMEOUT",
                    "final_url": page.url,
                    "matches": [],
                }

            except Exception as exc:
                log(
                    f"[{bookmaker}] homepage error: {exc} | elapsed={time.monotonic() - bookmaker_started:.1f}s"
                )

                return {
                    "bookmaker": bookmaker,
                    "status": "ERROR",
                    "final_url": page.url,
                    "matches": [],
                }

            title = page.title()

            body_text = safe_body_text(
                page
            )

            http_status = (
                response.status
                if response
                else 0
            )

            log(
                f"[{bookmaker}] "
                f"HTTP={http_status} "
                f"final={page.url} "
                f"text={len(body_text)}"
            )

            # ------------------------------------------------
            # PROTECTION
            # ------------------------------------------------

            if protection_detected(
                title,
                body_text,
                page.url,
            ):
                log(
                    f"[{bookmaker}] "
                    f"CAPTCHA/Cloudflare -> SKIP"
                )

                return {
                    "bookmaker": bookmaker,
                    "status": "CAPTCHA",
                    "final_url": page.url,
                    "matches": [],
                }

            # ------------------------------------------------
            # EACH TARGET MATCH
            # ------------------------------------------------

            all_confirmed = []

            for match in matches:

                # --------------------------------------------
                # A. Direct homepage rendered DOM check
                # --------------------------------------------

                verification = verify_page_for_match(
                    page,
                    match,
                    bookmaker,
                )

                if verification["status"] == "CAPTCHA":
                    return {
                        "bookmaker": bookmaker,
                        "status": "CAPTCHA",
                        "final_url": page.url,
                        "matches": [],
                    }

                for found in verification.get(
                    "matches",
                    [],
                ):
                    found["match"] = match
                    all_confirmed.append(
                        found
                    )

                if verification.get(
                    "matches"
                ):
                    continue

                # --------------------------------------------
                # B. Homepage -> event/sport links
                # --------------------------------------------

                candidate_links = (
                    collect_candidate_links(
                        page,
                        page.url,
                        match,
                    )
                )

                checked_links = set()

                for candidate_url in candidate_links[:25]:

                    if candidate_url in checked_links:
                        continue

                    checked_links.add(
                        candidate_url
                    )

                    try:
                        page.goto(
                            candidate_url,
                            wait_until="domcontentloaded",
                            timeout=BROWSER_TIMEOUT_MS,
                        )

                        page.wait_for_timeout(
                            min(
                                BROWSER_WAIT_MS,
                                3000,
                            )
                        )

                    except Exception:
                        continue

                    title = page.title()

                    body_text = safe_body_text(
                        page
                    )

                    if protection_detected(
                        title,
                        body_text,
                        page.url,
                    ):
                        log(
                            f"[{bookmaker}] "
                            f"protected event page -> skip"
                        )
                        continue

                    verification = verify_page_for_match(
                        page,
                        match,
                        bookmaker,
                    )

                    for found in verification.get(
                        "matches",
                        [],
                    ):
                        found["match"] = match

                        if not found.get(
                            "href"
                        ):
                            found["href"] = (
                                page.url
                            )

                        all_confirmed.append(
                            found
                        )

                    if verification.get(
                        "matches"
                    ):
                        break

                # --------------------------------------------
                # C. Internal search
                # --------------------------------------------

                if any(
                    x.get("match") == match
                    for x in all_confirmed
                ):
                    continue

                try:
                    page.goto(
                        homepage_url,
                        wait_until="domcontentloaded",
                        timeout=BROWSER_TIMEOUT_MS,
                    )

                    page.wait_for_timeout(
                        min(
                            BROWSER_WAIT_MS,
                            2500,
                        )
                    )

                except Exception:
                    continue

                search_result = internal_search(
                    page,
                    bookmaker,
                    match,
                )

                if search_result["status"] == "CAPTCHA":
                    continue

                for search_url in search_result.get(
                    "links",
                    []
                )[:20]:

                    try:
                        page.goto(
                            search_url,
                            wait_until="domcontentloaded",
                            timeout=BROWSER_TIMEOUT_MS,
                        )

                        page.wait_for_timeout(
                            min(
                                BROWSER_WAIT_MS,
                                3000,
                            )
                        )

                    except Exception:
                        continue

                    title = page.title()

                    body_text = safe_body_text(
                        page
                    )

                    if protection_detected(
                        title,
                        body_text,
                        page.url,
                    ):
                        continue

                    verification = verify_page_for_match(
                        page,
                        match,
                        bookmaker,
                    )

                    for found in verification.get(
                        "matches",
                        [],
                    ):
                        found["match"] = match

                        if not found.get(
                            "href"
                        ):
                            found["href"] = (
                                page.url
                            )

                        all_confirmed.append(
                            found
                        )

                    if verification.get(
                        "matches"
                    ):
                        break

            # ------------------------------------------------
            # DEDUP CONFIRMED RESULTS
            # ------------------------------------------------

            unique = {}

            for found in all_confirmed:
                match = found["match"]

                key = (
                    match["home_norm"],
                    match["away_norm"],
                    match["phase"],
                    found.get(
                        "href",
                        "",
                    ),
                )

                unique[key] = found

            confirmed = list(
                unique.values()
            )

            if confirmed:
                status = "CONFIRMED"
            else:
                status = "NOT_CONFIRMED"

            log(
                f"[{bookmaker}] status={status} confirmed={len(confirmed)} "
                f"elapsed={time.monotonic() - bookmaker_started:.1f}s"
            )

            return {
                "bookmaker": bookmaker,
                "status": status,
                "final_url": page.url,
                "matches": confirmed,
            }

    except Exception as exc:
        log(
            f"[{bookmaker}] UNHANDLED ERROR: {exc} | "
            f"elapsed={time.monotonic() - bookmaker_started:.1f}s"
        )
        log(traceback.format_exc())

        return {
            "bookmaker": bookmaker,
            "status": "ERROR",
            "final_url": homepage_url,
            "matches": [],
        }

    finally:
        cleanup_started = time.monotonic()

        try:
            if page:
                page.close(run_before_unload=False)
        except Exception as exc:
            log(f"[{bookmaker}] page close warning: {exc}")

        try:
            if context:
                context.close()
        except Exception as exc:
            log(f"[{bookmaker}] context close warning: {exc}")

        try:
            if browser:
                browser.close()
        except Exception as exc:
            log(f"[{bookmaker}] browser close warning: {exc}")

        log(
            f"[{bookmaker}] CLEANUP complete | "
            f"cleanup={time.monotonic() - cleanup_started:.2f}s | "
            f"total={time.monotonic() - bookmaker_started:.1f}s"
        )


# ============================================================
# BOOKMAKER SCAN
# ============================================================

def scan_bookmakers(matches):
    results = []

    if not matches:
        return results

    worker_count = max(
        1,
        min(
            MAX_BROWSER_WORKERS,
            len(BOOKMAKERS),
        ),
    )

    bookmakers_started = time.monotonic()

    log(
        f"[BOOKMAKERS] START | sites={len(BOOKMAKERS)} "
        f"workers={worker_count} matches={len(matches)}"
    )
    update_scanner_state(phase="BOOKMAKERS", last_error=None)

    with ThreadPoolExecutor(
        max_workers=worker_count
    ) as pool:

        futures = {}

        for bookmaker, url in BOOKMAKERS:
            future = pool.submit(
                browser_check_one,
                bookmaker,
                url,
                matches,
            )

            futures[future] = bookmaker

        for future in as_completed(
            futures
        ):
            bookmaker = futures[future]

            try:
                result = future.result()
                results.append(result)
                log(
                    f"[BOOKMAKERS] DONE | {bookmaker} | "
                    f"status={result.get('status')} | "
                    f"confirmed={len(result.get('matches', []))}"
                )

            except Exception as exc:
                log(
                    f"[BOOKMAKERS] "
                    f"{bookmaker} worker error: "
                    f"{exc}"
                )

                results.append(
                    {
                        "bookmaker": bookmaker,
                        "status": "ERROR",
                        "final_url": "",
                        "matches": [],
                    }
                )

    log(
        f"[BOOKMAKERS] ALL DONE | elapsed={time.monotonic() - bookmakers_started:.1f}s | "
        f"results={len(results)}"
    )
    return results


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send_test_message():
    """Send one diagnostic Telegram message when the process starts."""
    message = (
        "🧪 TEST MESSAGE\n\n"
        "أهلاً بك يا ديلوفان.\n\n"
        f"✅ {APP_VERSION}\n"
        "✅ Telegram test message sent successfully.\n"
        "🕒 " + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    log("[TEST] Sending Telegram test message...")
    ok = telegram_send(message)

    if ok:
        log("[TEST] Telegram test message delivered successfully")
    else:
        log("[TEST] Telegram test message FAILED")

    return ok


def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN:
        log(
            "[TELEGRAM] "
            "TELEGRAM_BOT_TOKEN missing"
        )
        return False

    if not TELEGRAM_CHAT_ID:
        log(
            "[TELEGRAM] "
            "TELEGRAM_CHAT_ID missing"
        )
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=15,
        )

        if response.status_code != 200:
            log(
                f"[TELEGRAM] HTTP="
                f"{response.status_code}"
            )
            return False

        data = response.json()

        if data.get("ok") is True:
            log(
                "[TELEGRAM] "
                "Message delivered successfully"
            )
            return True

        log(
            f"[TELEGRAM] API rejected message: "
            f"{data}"
        )

        return False

    except Exception as exc:
        log(
            f"[TELEGRAM] ERROR: {exc}"
        )
        return False


# ============================================================
# ALERT KEY
# ============================================================

def match_key(match):
    return (
        match["home_norm"],
        match["away_norm"],
        match["phase"],
        match["home_score"],
        match["away_score"],
    )


def alert_key(bookmaker, match):
    return (
        bookmaker,
        match_key(match),
    )


# ============================================================
# ALERT
# ============================================================

def send_same_match_alert(
    bookmaker_result,
    found,
):
    match = found.get(
        "match"
    )

    if not match:
        return False

    bookmaker = bookmaker_result[
        "bookmaker"
    ]

    key = alert_key(
        bookmaker,
        match,
    )

    # --------------------------------------------------------
    # CHECK DUPLICATE WITHOUT RESERVING THE KEY
    # --------------------------------------------------------

    with sent_alerts_lock:
        if key in sent_alerts:
            log(
                f"[ALERT] Duplicate skipped: "
                f"{bookmaker} | "
                f"{match['home']} - "
                f"{match['away']}"
            )
            return False

    event_url = clean_text(
        found.get(
            "href",
            "",
        )
    )

    if not event_url:
        event_url = clean_text(
            bookmaker_result.get(
                "final_url",
                "",
            )
        )

    confidence = found.get(
        "score",
        0.0,
    )

    status = found.get(
        "status",
        "PREMATCH",
    )

    message = (
        "⚽ SAME MATCH PREMATCH\n\n"
        f"🏠 {match['home']}\n"
        f"🆚 {match['away']}\n"
        f"📊 Kooora: "
        f"{match['home_score']} - "
        f"{match['away_score']} "
        f"({match['phase']})\n\n"
        f"🎯 Bookmaker: {bookmaker}\n"
        f"🔎 Status: {status}\n"
        f"🎯 Match confidence: "
        f"{confidence:.2f}\n"
        f"🧩 Verification: "
        f"{found.get('source', 'LOCAL_EVENT')}\n"
        f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"🔗 {event_url}"
    )

    # --------------------------------------------------------
    # TELEGRAM FIRST
    # --------------------------------------------------------

    telegram_ok = telegram_send(
        message
    )

    if not telegram_ok:
        log(
            "[ALERT] Telegram failed -> "
            "sent_alerts NOT updated"
        )

        return False

    # --------------------------------------------------------
    # ONLY AFTER SUCCESS
    # --------------------------------------------------------

    with sent_alerts_lock:
        sent_alerts.add(key)

    log(
        f"[ALERT] Successfully recorded: "
        f"{bookmaker} | "
        f"{match['home']} - "
        f"{match['away']}"
    )

    return True


# ============================================================
# PROCESS ONE SCAN
# ============================================================

def process_scan():
    started = time.monotonic()
    scan_started_wall = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    update_scanner_state(
        active=True,
        phase="STARTING",
        scan_started_at=scan_started_wall,
        last_scan_started_at=scan_started_wall,
        last_error=None,
    )

    log("\n==================================================")
    log(f"[SCAN] START {scan_started_wall}")

    # --------------------------------------------------------
    # KOOORA FETCH
    # --------------------------------------------------------
    update_scanner_state(phase="KOOORA_FETCH")
    kooora_started = time.monotonic()
    log("[SCAN] Kooora fetch START")

    html = fetch_kooora_html()
    kooora_elapsed = time.monotonic() - kooora_started

    if not html:
        log(f"[SCAN] Kooora fetch FAILED | elapsed={kooora_elapsed:.2f}s")
        update_scanner_state(
            active=False,
            phase="IDLE",
            last_scan_finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_scan_duration_seconds=round(time.monotonic() - started, 2),
            last_kooora_matches=0,
            last_bookmaker_results=0,
            last_error="Kooora unavailable",
        )
        log("==================================================")
        return False

    log(f"[SCAN] Kooora fetch DONE | elapsed={kooora_elapsed:.2f}s | html={len(html)}")

    # --------------------------------------------------------
    # KOOORA PARSE
    # --------------------------------------------------------
    update_scanner_state(phase="KOOORA_PARSE")
    parse_started = time.monotonic()
    log("[SCAN] Kooora parsing START")

    matches = parse_kooora(html)
    parse_elapsed = time.monotonic() - parse_started
    update_scanner_state(last_kooora_matches=len(matches))

    log(f"[SCAN] Kooora parsing DONE | elapsed={parse_elapsed:.2f}s | matches={len(matches)}")

    if not matches:
        finished = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total = time.monotonic() - started
        update_scanner_state(
            active=False,
            phase="IDLE",
            last_scan_finished_at=finished,
            last_successful_scan_at=finished,
            last_scan_duration_seconds=round(total, 2),
            last_bookmaker_results=0,
            last_error=None,
        )
        log(f"[SCAN] No Kooora HT/FT matches | total={total:.2f}s")
        log("==================================================")
        return True

    log(
        f"[SCAN] Checking {len(matches)} Kooora HT/FT matches against "
        f"{len(BOOKMAKERS)} bookmakers"
    )
    log(f"[SCAN] Strict confidence >= {MIN_MATCH_CONFIDENCE:.2f}")

    # --------------------------------------------------------
    # BOOKMAKERS
    # --------------------------------------------------------
    bookmaker_started = time.monotonic()
    results = scan_bookmakers(matches)
    bookmaker_elapsed = time.monotonic() - bookmaker_started
    update_scanner_state(
        phase="RESULT_PROCESSING",
        last_bookmaker_results=len(results),
    )
    log(f"[SCAN] Bookmaker phase DONE | elapsed={bookmaker_elapsed:.2f}s | results={len(results)}")

    confirmed = 0
    alerts_sent = 0
    status_counts = {}

    # --------------------------------------------------------
    # RESULTS / TELEGRAM
    # --------------------------------------------------------
    result_started = time.monotonic()
    for result in results:
        status = result.get("status", "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1

        for found in result.get("matches", []):
            if found.get("status") not in {
                "PREMATCH",
                "SCHEDULED_TIME",
            }:
                continue

            confirmed += 1

            if send_same_match_alert(result, found):
                alerts_sent += 1

    result_elapsed = time.monotonic() - result_started
    total = time.monotonic() - started
    finished = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    update_scanner_state(
        active=False,
        phase="IDLE",
        last_scan_finished_at=finished,
        last_successful_scan_at=finished,
        last_scan_duration_seconds=round(total, 2),
        last_error=None,
    )

    log(
        f"[SCAN] Result/Telegram phase DONE | elapsed={result_elapsed:.2f}s"
    )
    log(
        f"[SCAN] DONE | total={total:.2f}s | "
        f"bookmaker_statuses={status_counts} | "
        f"confirmed={confirmed} | alerts_sent={alerts_sent}"
    )
    log("==================================================")
    return True


# ============================================================
# SCANNER LOOP
# ============================================================

def scanner_loop():
    log(
        f"[START] {APP_VERSION}"
    )

    log(
        "[START] "
        "Kooora HT/FT -> "
        "strict bookmaker PREMATCH verification"
    )

    log(
        f"[START] "
        f"interval={SCAN_SECONDS}s"
    )

    log(
        f"[START] "
        f"MAX_BROWSER_WORKERS="
        f"{MAX_BROWSER_WORKERS}"
    )

    log(
        f"[START] "
        f"MIN_MATCH_CONFIDENCE="
        f"{MIN_MATCH_CONFIDENCE}"
    )

    log(
        f"[START] Playwright="
        f"{'AVAILABLE' if PLAYWRIGHT_AVAILABLE else 'NOT INSTALLED'}"
    )
    log(f"[START] HTTP_TIMEOUT={HTTP_TIMEOUT}s | BROWSER_TIMEOUT_MS={BROWSER_TIMEOUT_MS} | BROWSER_WAIT_MS={BROWSER_WAIT_MS}ms")
    log("[START] Health endpoint: /health")

    if not PLAYWRIGHT_AVAILABLE:
        log(
            "[START] WARNING: "
            "Bookmaker browser verification is disabled "
            "because Playwright is unavailable."
        )

    # --------------------------------------------------------
    # ELAPSED-TIME COMPENSATION
    #
    # Example:
    # cycle starts at 12:00:00
    # scan takes 47 seconds
    # sleep only 13 seconds
    # next cycle starts at 12:01:00
    #
    # If scan takes 75 seconds:
    # sleep = 0
    # next cycle starts immediately.
    # --------------------------------------------------------

    next_cycle = time.monotonic()

    while True:

        cycle_started = time.monotonic()

        try:

            # Avoid overlapping scanner executions.
            acquired = scan_lock.acquire(
                blocking=False
            )

            if not acquired:
                log(
                    "[SCAN] Previous scan still running -> skip overlap"
                )

            else:
                try:
                    process_scan()

                finally:
                    scan_lock.release()

        except Exception as exc:
            finished = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            update_scanner_state(
                active=False,
                phase="IDLE",
                last_scan_finished_at=finished,
                last_scan_duration_seconds=round(time.monotonic() - cycle_started, 2),
                last_error=str(exc),
            )
            log(f"[SCAN] UNHANDLED ERROR: {exc}")
            log(traceback.format_exc())

        # ----------------------------------------------------
        # Calculate exact next cycle.
        # ----------------------------------------------------

        next_cycle += SCAN_SECONDS

        now = time.monotonic()

        sleep_for = (
            next_cycle - now
        )

        if sleep_for > 0:
            log(
                f"[SCAN] "
                f"Next cycle in "
                f"{sleep_for:.1f}s"
            )

            time.sleep(
                sleep_for
            )

        else:
            # Scan took longer than interval.
            # Do not add another full 60 seconds.
            log(
                "[SCAN] "
                "Cycle exceeded interval -> "
                "starting next cycle immediately"
            )

            # Reset schedule to avoid accumulating
            # large negative drift.
            next_cycle = time.monotonic()


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

    log(
        f"[MAIN] Starting "
        f"{APP_VERSION}"
    )

    # --------------------------------------------------------
    # STARTUP TESTS
    # --------------------------------------------------------
    log(
        "--- [TEST MESSAGE] V3.3 Diagnostic: "
        "نظام الفحص يعمل بشكل سليم ---"
    )
    telegram_send_test_message()

    # One scanner thread only.
    scanner_thread = threading.Thread(
        target=scanner_loop,
        daemon=True,
        name="kooora-scanner",
    )

    scanner_thread.start()

    # One Flask application.
    # No debug.
    # No reloader.
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )
