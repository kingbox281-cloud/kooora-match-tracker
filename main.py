import os

# Keep Playwright browsers inside the application environment on Render.
# IMPORTANT: this must be set BEFORE importing Playwright.
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

import re
import time
import threading
import unicodedata
import gc
import multiprocessing as mp
import resource
from pathlib import Path
from datetime import datetime

import traceback
from urllib.parse import urljoin, urlparse, quote
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from flask import Flask

try:
    from playwright.async_api import (
        async_playwright,
        TimeoutError as PlaywrightTimeoutError,
    )
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False


# ============================================================
# KOOORA MATCH TRACKER
# VERSION 3.13
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
# MEMORY SAFETY
# ============================================================

def memory_mb():
    try:
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except Exception:
        return 0.0


def log_memory(label):
    log(f"[MEMORY] {label} | peak_rss={memory_mb():.1f} MB | cgroup={cgroup_memory_mb():.1f} MB")


def cgroup_memory_mb():
    """Best-effort total container memory, including Chromium child processes."""
    paths = (
        "/sys/fs/cgroup/memory.current",
        "/sys/fs/cgroup/memory/memory.usage_in_bytes",
    )
    for path in paths:
        try:
            raw = Path(path).read_text().strip()
            if raw and raw.isdigit():
                return int(raw) / (1024.0 * 1024.0)
        except Exception:
            continue
    return 0.0


def memory_guarded(limit_mb=380.0):
    current = cgroup_memory_mb()
    if current and current >= limit_mb:
        log(
            f"[MEMORY GUARD] current={current:.1f} MB >= limit={limit_mb:.1f} MB"
        )
        return True
    return False


# ============================================================
# CONFIG
# ============================================================

APP_VERSION = "KOOORA_BROWSER_V3_20_FREE_FAST_FAIL"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

KOOORA_URL = "https://www.kooora.com/كرة القدم/مباريات-اليوم"
KOOORA_FALLBACK_URL = "https://www.kooora.com/default.aspx?g=matches"

SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "60"))

BROWSER_TIMEOUT_MS = int(
    os.getenv("BROWSER_TIMEOUT_MS", "20000")
)

BROWSER_WAIT_MS = int(
    os.getenv("BROWSER_WAIT_MS", "0")
)

MAX_BROWSER_WORKERS = int(
    os.getenv("MAX_BROWSER_WORKERS", "1")
)

MIN_MATCH_CONFIDENCE = float(
    os.getenv("MIN_MATCH_CONFIDENCE", "0.92")
)

ONE_WORD_EXACT_CONFIDENCE = 0.93

# Maximum character distance used by the strict text fallback.
EVENT_WINDOW_CHARS = int(
    os.getenv("EVENT_WINDOW_CHARS", "900")
)

# Free Render is only 512 MB, so the free profile deliberately trades
# breadth/depth for stability and accepts more false-negative skips.
FREE_MODE = os.getenv("FREE_MODE", "1").strip() == "1"
FREE_MEMORY_GUARD_MB = float(os.getenv("FREE_MEMORY_GUARD_MB", "380"))
FREE_BOOKMAKER_BATCH_SIZE = int(os.getenv("FREE_BOOKMAKER_BATCH_SIZE", "2"))
FREE_BOOKMAKER_HARD_TIMEOUT_SECONDS = int(
    os.getenv("FREE_BOOKMAKER_HARD_TIMEOUT_SECONDS", "9")
)
KOOORA_HARD_TIMEOUT_SECONDS = int(
    os.getenv("KOOORA_HARD_TIMEOUT_SECONDS", "25")
)
MAX_DISCOVERY_LINKS = int(os.getenv("MAX_DISCOVERY_LINKS", "5" if FREE_MODE else "30"))
MAX_CANDIDATE_PAGES_PER_MATCH = int(os.getenv("MAX_CANDIDATE_PAGES_PER_MATCH", "3" if FREE_MODE else "25"))
MAX_SEARCH_VARIANTS = int(os.getenv("MAX_SEARCH_VARIANTS", "1" if FREE_MODE else "3"))
MAX_SEARCH_INPUTS = int(os.getenv("MAX_SEARCH_INPUTS", "1" if FREE_MODE else "3"))
MAX_SEARCH_LINKS = int(os.getenv("MAX_SEARCH_LINKS", "2" if FREE_MODE else "20"))
MAX_EVENT_BLOCKS_FREE = int(os.getenv("MAX_EVENT_BLOCKS_FREE", "120"))

# Maximum number of candidate DOM event blocks inspected.
MAX_EVENT_BLOCKS = int(
    os.getenv("MAX_EVENT_BLOCKS", str(MAX_EVENT_BLOCKS_FREE if FREE_MODE else 500))
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

# V3.10 safety guard:
# Never allow two Chromium instances to launch at the same time,
# even if a future code path accidentally creates concurrent
# bookmaker tasks. This is intentionally independent of the
# scanner lock.
browser_launch_lock = threading.Lock()
bookmaker_rotation_lock = threading.Lock()
bookmaker_rotation_index = 0


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
        "playwright_browsers_path": os.environ.get(
            "PLAYWRIGHT_BROWSERS_PATH", ""
        ),
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
    """
    Conservative marker detection.

    Short markers (ft / ht / live) are matched as tokens so that a random
    substring inside a team name, URL, or unrelated word cannot change the
    event status.
    """
    low = clean_text(text).lower()
    if not low:
        return False

    for marker in markers:
        marker = clean_text(marker).lower()
        if not marker:
            continue

        # Very short markers must be token/boundary based.
        if marker in {"ft", "ht", "live"}:
            if re.search(rf"(?<![\w]){re.escape(marker)}(?![\w])", low):
                return True
            continue

        # Arabic / multi-word markers and normal phrases.
        if marker in low:
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

def _kooora_fetch_worker(url, headers, connect_timeout, read_timeout, conn):
    """
    Isolated worker so a stuck network call can be force-terminated by
    the parent process. This provides a true wall-clock bound for Kooora.
    """
    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=(connect_timeout, read_timeout),
        )
        conn.send({
            "ok": True,
            "status_code": response.status_code,
            "url": response.url,
            "text": response.text,
        })
    except Exception as exc:
        try:
            conn.send({
                "ok": False,
                "error": str(exc),
            })
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def fetch_kooora_html():
    """Fetch Kooora directly in the main process with bounded requests timeouts.

    V3.17 deliberately removes the fork/multiprocessing worker used by V3.15.
    V3.16 proved that Render can reach Kooora with ordinary requests, while the
    forked worker was the part that hung. Each URL therefore gets a normal
    requests timeout and the next URL is tried on failure.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ar,en;q=0.8",
        "Connection": "close",
    }

    urls = [KOOORA_URL, KOOORA_FALLBACK_URL]
    timeout = max(5, min(20, int(KOOORA_HARD_TIMEOUT_SECONDS)))

    for url in urls:
        started = time.monotonic()
        try:
            log(f"[KOOORA] DIRECT REQUEST START url={url} timeout={timeout}s")
            response = requests.get(
                url,
                headers=headers,
                timeout=(min(8, timeout), timeout),
                allow_redirects=True,
            )
            elapsed = time.monotonic() - started
            html = response.text or ""
            log(
                f"[KOOORA] HTTP={response.status_code} "
                f"url={response.url} length={len(html)} elapsed={elapsed:.2f}s"
            )
            if response.status_code == 200 and len(html) >= 1000:
                return html
        except requests.exceptions.Timeout as exc:
            log(f"[KOOORA] REQUEST TIMEOUT url={url} elapsed={time.monotonic()-started:.2f}s error={exc}")
        except requests.exceptions.RequestException as exc:
            log(f"[KOOORA] REQUEST ERROR url={url} elapsed={time.monotonic()-started:.2f}s error={exc}")
        except Exception as exc:
            log(f"[KOOORA] UNEXPECTED ERROR url={url} elapsed={time.monotonic()-started:.2f}s error={exc}")

    return ""

def extract_score(text):
    text = clean_text(text)

    patterns = [
        r"\b(\d{1,2})\s*[-:]\s*(\d{1,2})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1)), int(match.group(2))

    return None, None


def _kooora_attribute_text(tag):
    """Collect status/phase-like DOM attributes from a Kooora card."""
    values = []

    try:
        for key in (
            "data-match-status", "data-status", "data-phase", "data-period",
            "data-state", "data-match-state", "data-match-phase",
            "aria-label", "title", "alt", "class",
        ):
            value = tag.get(key, "")
            if isinstance(value, (list, tuple)):
                value = " ".join(str(x) for x in value)
            if value:
                values.append(str(value))
    except Exception:
        pass

    # Also inspect descendants whose class/id suggests status/phase/state.
    try:
        for child in tag.find_all(True):
            attrs = " ".join(
                str(child.get(k, ""))
                for k in ("class", "id", "data-status", "data-phase", "data-period", "data-state")
            ).lower()
            if any(x in attrs for x in ("status", "phase", "period", "state", "minute", "timer")):
                txt = clean_text(child.get_text(" ", strip=True))
                if txt:
                    values.append(txt)
                for k in ("data-status", "data-phase", "data-period", "data-state", "aria-label", "title"):
                    v = child.get(k, "")
                    if v:
                        values.append(str(v))
    except Exception:
        pass

    return clean_text(" | ".join(values))


def _kooora_has_explicit_marker(text, markers):
    return contains_marker(text, markers)


def detect_kooora_phase(card, status, text):
    """
    Conservative Kooora phase detection.

    Priority:
      1) explicit result card -> FT
      2) explicit HT/halftime marker -> HT
      3) explicit FT marker -> FT
      4) otherwise unknown

    Generic words such as 'final' are deliberately NOT enough on a LIVE card,
    because league/navigation text can contain them and create false FT states.
    """
    if status == "RESULT":
        return "FT"

    attr_text = _kooora_attribute_text(card)
    combined = clean_text(f"{attr_text} | {text}").lower()

    ht_markers = [
        "ht", "half time", "halftime", "half-time", "halbzeit", "pause",
        "الشوط الأول", "الشوط الاول", "بين الشوطين", "استراحة",
        "نهاية الشوط الأول", "نهاية الشوط الاول", "نصف الوقت",
    ]
    ft_markers = [
        "انتهت", "انتهى", "full time", "full-time", "finished",
        "match ended", "spiel beendet", "beendet", "endstand", "abpfiff",
        "النهاية", "انتهت المباراة", "انتهى اللقاء", "نهاية المباراة",
    ]

    # On a LIVE card, HT is the first valid state. Do not use generic
    # 'final'/'finish' words from unrelated page text.
    if status == "LIVE":
        if _kooora_has_explicit_marker(combined, ht_markers):
            return "HT"
        if _kooora_has_explicit_marker(combined, ft_markers):
            return "FT"
        return ""

    # For cards without a reliable data status, explicit markers still work.
    if _kooora_has_explicit_marker(combined, ht_markers):
        return "HT"
    if _kooora_has_explicit_marker(combined, ft_markers):
        return "FT"

    return ""


def extract_kooora_score(card, text):
    """Try visible text first, then score-like DOM attributes/elements."""
    score = extract_score(text)
    if score != (None, None):
        return score

    try:
        for child in card.find_all(True):
            attrs = " ".join(
                str(child.get(k, ""))
                for k in ("class", "id", "data-score", "data-home-score", "data-away-score")
            ).lower()
            if not any(x in attrs for x in ("score", "result", "goals")):
                continue

            values = []
            for k in ("data-score", "data-home-score", "data-away-score"):
                v = child.get(k, "")
                if v != "":
                    values.append(str(v))
            values.append(child.get_text(" ", strip=True))
            sc = extract_score(clean_text(" ".join(values)))
            if sc != (None, None):
                return sc
    except Exception:
        pass

    return None, None


def extract_team_candidates(card):
    """Extract likely team names while filtering navigation/status noise."""
    selectors = [
        ".fco-team-name",
        ".fco-team-name a",
        "[class*='team-name']",
        "[class*='teamName']",
        "[class*='participant']",
        "[class*='competitor']",
        "[data-team-name]",
    ]

    candidates = []
    seen = set()

    def add(value):
        value = clean_text(value)
        if not value:
            return

        value = re.sub(
            r"\b(?:FT|HT|LIVE|FIXTURE|RESULT|PREMATCH|SCHEDULED)\b",
            " ", value, flags=re.I
        )
        value = clean_text(value)
        if not value:
            return

        if re.fullmatch(r"\d{1,2}\s*[-:]\s*\d{1,2}", value):
            return

        norm = normalize_team(value)
        if len(norm) < 2 or norm in seen:
            return

        # Reject obvious status/navigation fragments.
        low = norm.lower()
        bad = {
            "مباريات اليوم", "النتائج", "والنتائج", "الدوري", "الإنجليزي",
            "الممتاز", "today", "matches", "results", "football", "soccer",
        }
        if low in bad:
            return

        seen.add(norm)
        candidates.append(value)

    # Prefer explicit team-name/data-team-name elements.
    for selector in selectors:
        try:
            for element in card.select(selector):
                value = element.get("data-team-name", "") or element.get_text(" ", strip=True)
                add(value)
        except Exception:
            continue

    # Last-resort fallback: only links with team-like class/id, not every link.
    if len(candidates) < 2:
        try:
            for element in card.find_all("a"):
                attrs = " ".join(str(element.get(k, "")) for k in ("class", "id", "href")).lower()
                if any(x in attrs for x in ("team", "participant", "competitor", "club")):
                    add(element.get_text(" ", strip=True))
        except Exception:
            pass

    return candidates


def parse_kooora(html):
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")

    cards = soup.select(".fco-match-list-item")
    if not cards:
        cards = soup.select("[data-match-status]")

    if not cards:
        log("[KOOORA] No match cards found")
        return []

    matches = []
    counts = {"FIXTURE": 0, "LIVE": 0, "RESULT": 0}
    skip_counts = {"NO_SCORE": 0, "NO_TEAMS": 0, "NO_PHASE": 0}

    for card in cards:
        try:
            status = clean_text(card.get("data-match-status", "")).upper()
            if status in counts:
                counts[status] += 1

            text = clean_text(card.get_text(" ", strip=True))
            phase = detect_kooora_phase(card, status, text)
            candidates = extract_team_candidates(card)

            if len(candidates) < 2:
                if status == "LIVE":
                    skip_counts["NO_TEAMS"] += 1
                continue

            home, away = candidates[0], candidates[1]
            home_norm, away_norm = normalize_team(home), normalize_team(away)
            if not home_norm or not away_norm or home_norm == away_norm:
                skip_counts["NO_TEAMS"] += 1
                continue

            home_score, away_score = extract_kooora_score(card, text)

            # FT must have a confirmed score. HT may legitimately lack a
            # parsed score because the live score can be rendered separately.
            if phase == "FT" and (home_score is None or away_score is None):
                skip_counts["NO_SCORE"] += 1
                continue

            if phase not in {"HT", "FT"}:
                if status == "LIVE":
                    skip_counts["NO_PHASE"] += 1
                    if skip_counts["NO_PHASE"] <= 5:
                        attr = _kooora_attribute_text(card)
                        log(
                            f"[KOOORA DEBUG] LIVE no HT/FT phase | "
                            f"attrs={attr[:180]} | text={text[:220]}"
                        )
                continue

            matches.append({
                "home": home,
                "away": away,
                "home_norm": home_norm,
                "away_norm": away_norm,
                "home_score": home_score,
                "away_score": away_score,
                "phase": phase,
            })

        except Exception as exc:
            log(f"[KOOORA] card parse error: {exc}")

    unique = {}
    for match in matches:
        key = (
            match["home_norm"], match["away_norm"], match["phase"],
            match["home_score"], match["away_score"],
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
            f"[KOOORA] {match['phase']} {match['home']} "
            f"{match['home_score']}-{match['away_score']} {match['away']}"
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


FAST_BLOCK_URL_MARKERS = (
    "/restrict/block",
    "/access-denied",
    "/access_denied",
    "/forbidden",
    "/blocked",
    "/block/index",
    "accessdenied",
    "zugriff-verweigert",
)


def fast_http_rejection_status(status_code):
    return status_code in {401, 403, 429, 451}


def fast_block_url(url):
    low = clean_text(url).lower()
    return any(marker in low for marker in FAST_BLOCK_URL_MARKERS)


async def safe_body_text(page):
    try:
        return clean_text(
            await page.locator(
                "body"
            ).inner_text(
                timeout=1500
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


async def get_event_blocks(page):
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
            '[data-event-id]',
            '[data-match-id]',
            '[data-fixture-id]',
            '[data-testid*="fixture"]',
            '[data-testid*="event"]',
            '[data-testid*="match"]'
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
                    if (rect.width === 0 || rect.height === 0) continue;

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

                    const key = text + "|" + (links[0]?.href || "");
                    if (seen.has(key)) continue;
                    seen.add(key);

                    output.push({
                        text: text,
                        href: links[0]?.href || "",
                        selector: selector
                    });

                    if (output.length >= 500) return output;
                } catch (_) {
                    continue;
                }
            }
        }

        return output;
    }
    """

    try:
        blocks = await page.evaluate(script)
        if not isinstance(blocks, list):
            return []
        return blocks[:MAX_EVENT_BLOCKS]
    except Exception as exc:
        log(f"[BROWSER] event block extraction error: {exc}")
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

    # Locate token occurrences with token boundaries.
    # This prevents "live", "ft", or team fragments from matching inside
    # unrelated words.
    positions = []

    for token in set(home_tokens + away_tokens):
        if not token:
            continue

        pattern = re.compile(
            rf"(?<![\w]){re.escape(token)}(?![\w])",
            flags=re.I,
        )

        for found in pattern.finditer(text_norm):
            positions.append((found.start(), token))

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


async def collect_links(page):
    try:
        links = await page.locator(
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


async def collect_candidate_links(
    page,
    base_url,
    match,
):
    """Memory-safe event-link discovery.

    The old implementation first copied every <a> element into Python,
    which can be a very large list on bookmaker homepages. Free mode now
    filters inside the browser and returns only a tiny bounded set.
    """
    home_terms = meaningful_tokens(match.get("home", ""))
    away_terms = meaningful_tokens(match.get("away", ""))
    limit = max(1, MAX_DISCOVERY_LINKS)

    keywords = [
        "football", "soccer", "sport", "fussball", "fußball",
        "match", "matches", "event", "events", "fixture", "fixtures",
        "game", "games", "wetten", "bet", "prematch", "pre-match", "live",
    ]

    script = """
    (data) => {
        const out = [];
        const seen = new Set();
        const anchors = document.querySelectorAll('a[href]');

        for (const a of anchors) {
            if (out.length >= data.limit) break;
            const href = a.href || '';
            const text = (a.innerText || '').replace(/\\s+/g, ' ').trim();
            if (!href || href.startsWith('javascript:') || href.startsWith('mailto:') || href.startsWith('tel:')) continue;

            const combined = (href + ' ' + text).toLowerCase();
            const sport = data.keywords.some(k => combined.includes(k));
            const team = [...data.homeTerms, ...data.awayTerms].some(t => t && combined.includes(t));
            if (!sport && !team) continue;
            if (seen.has(href)) continue;
            seen.add(href);
            out.push({href, text});
        }
        return out;
    }
    """

    try:
        links = await page.locator("a[href]").evaluate_all(
            script,
            {
                "limit": limit,
                "keywords": keywords,
                "homeTerms": home_terms,
                "awayTerms": away_terms,
            },
        )
    except Exception:
        return []

    if not isinstance(links, list):
        return []

    candidates = []
    seen = set()
    for link in links:
        href = clean_text(link.get("href", ""))
        if not href:
            continue
        absolute = urljoin(base_url, href)
        if not same_domain(base_url, absolute):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        candidates.append(absolute)
        if len(candidates) >= limit:
            break
    return candidates


# ============================================================
# INTERNAL SEARCH
# ============================================================

def _deadline_remaining_ms(deadline):
    if deadline is None:
        return 10_000_000
    return max(0, int((deadline - time.monotonic()) * 1000))


async def find_search_inputs(page):
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
            locator = page.locator(selector)
            count = await locator.count()

            for index in range(min(count, 5)):
                result.append(locator.nth(index))

        except Exception:
            continue

    return result


async def internal_search(
    page,
    bookmaker,
    match,
    homepage_url,
    deadline=None,
):
    """
    Try normal visible-site search controls without exceeding the bookmaker
    deadline. No API reverse engineering and no CAPTCHA bypass.
    """

    searches = [
        (match["home"], match["away"]),
        (match["away"], match["home"]),
        (f"{match['home']} {match['away']}", ""),
    ]

    for first, second in searches[:MAX_SEARCH_VARIANTS]:
        if _deadline_remaining_ms(deadline) < 1000:
            return {"status": "HARD_TIMEOUT", "links": []}

        try:
            timeout_ms = max(1000, min(BROWSER_TIMEOUT_MS, _deadline_remaining_ms(deadline)))
            await page.goto(
                homepage_url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            wait_ms = min(1500, BROWSER_WAIT_MS, max(0, _deadline_remaining_ms(deadline) - 250))
            if wait_ms > 0:
                await page.wait_for_timeout(wait_ms)

        except Exception:
            pass

        if _deadline_remaining_ms(deadline) < 1000:
            return {"status": "HARD_TIMEOUT", "links": []}

        inputs = await find_search_inputs(page)
        if not inputs:
            continue

        for search_input in inputs[:MAX_SEARCH_INPUTS]:
            if _deadline_remaining_ms(deadline) < 1000:
                return {"status": "HARD_TIMEOUT", "links": []}
            try:
                await search_input.fill("")
                await search_input.fill(first)
                await search_input.press("Enter")

                wait_ms = min(2500, max(0, _deadline_remaining_ms(deadline) - 250))
                if wait_ms > 0:
                    await page.wait_for_timeout(wait_ms)

                title = await page.title()
                text = await safe_body_text(page)

                if protection_detected(title, text, page.url):
                    log(f"[{bookmaker}] CAPTCHA/protection during internal search")
                    return {"status": "CAPTCHA", "links": []}

                links = await collect_candidate_links(page, page.url, match)
                if links:
                    return {
                        "status": "SEARCH_FOUND",
                        "links": links[:MAX_SEARCH_LINKS],
                    }

            except Exception:
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


async def verify_page_for_match(
    page,
    match,
    bookmaker,
):
    """
    Verify current rendered page.

    NEVER classify the whole page as PREMATCH.
    """

    title = await page.title()

    body_text = await safe_body_text(
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

    event_blocks = await get_event_blocks(
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

async def browser_check_one_async(
    bookmaker,
    homepage_url,
    matches,
):
    """One Chromium instance per bookmaker using Playwright Async API."""

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
    playwright = None
    bookmaker_started = time.monotonic()
    deadline = bookmaker_started + FREE_BOOKMAKER_HARD_TIMEOUT_SECONDS

    log(f"[{bookmaker}] START | targets={len(matches)} | timeout={FREE_BOOKMAKER_HARD_TIMEOUT_SECONDS}s")

    try:
        def timed_out():
            return _deadline_remaining_ms(deadline) < 750

        def goto_timeout_ms():
            return max(1000, min(BROWSER_TIMEOUT_MS, _deadline_remaining_ms(deadline)))

        if timed_out():
            return {
                "bookmaker": bookmaker,
                "status": "HARD_TIMEOUT",
                "final_url": homepage_url,
                "matches": [],
            }

        if FREE_MODE and memory_guarded(FREE_MEMORY_GUARD_MB):
            return {
                "bookmaker": bookmaker,
                "status": "MEMORY_GUARD",
                "final_url": homepage_url,
                "matches": [],
            }

        # Start the async Playwright runtime directly.
        # This object exposes the documented async stop() method.
        playwright = await async_playwright().start()

        log(
            f"[{bookmaker}] Launching Chromium | "
            f"PLAYWRIGHT_BROWSERS_PATH={os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')}"
        )

        # V3.10: serialize Chromium launches.
        # MAX_BROWSER_WORKERS=1 already limits bookmaker concurrency,
        # but this extra guard protects against accidental overlap.
        acquired_browser_launch = browser_launch_lock.acquire(
            blocking=False
        )

        if not acquired_browser_launch:
            log(
                f"[{bookmaker}] Chromium launch blocked -> "
                f"another browser is already active"
            )
            return {
                "bookmaker": bookmaker,
                "status": "BROWSER_BUSY",
                "final_url": homepage_url,
                "matches": [],
            }

        try:
            browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-extensions",
                    "--disable-features=Translate,BackForwardCache,TranslateUI,MediaRouter,OptimizationHints",
                    "--disable-component-update",
                    "--disable-default-apps",
                    "--disable-sync",
                    "--no-pings",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
        finally:
            browser_launch_lock.release()

        context = await browser.new_context(
            viewport={"width": 1024, "height": 600},
            service_workers="block",
            locale="de-DE",
            timezone_id="Europe/Berlin",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )

        page = await context.new_page()

        # Memory-safe browsing: keep scripts/styles/HTML, but avoid large
        # image, media and font payloads that do not help event verification.
        async def _memory_route(route):
            try:
                resource_type = route.request.resource_type
                if resource_type in {"image", "media", "font"}:
                    await route.abort()
                else:
                    await route.continue_()
            except Exception:
                try:
                    await route.continue_()
                except Exception:
                    pass

        await context.route("**/*", _memory_route)
        context.set_default_timeout(4000)
        context.set_default_navigation_timeout(min(BROWSER_TIMEOUT_MS, 8000))
        log_memory(f"{bookmaker} after context/page setup")

        try:
            if timed_out():
                return {
                    "bookmaker": bookmaker,
                    "status": "HARD_TIMEOUT",
                    "final_url": homepage_url,
                    "matches": [],
                }
            response = await page.goto(
                homepage_url,
                wait_until="domcontentloaded",
                timeout=goto_timeout_ms(),
            )

        except PlaywrightTimeoutError:
            log(
                f"[{bookmaker}] homepage timeout | "
                f"elapsed={time.monotonic() - bookmaker_started:.1f}s"
            )
            return {
                "bookmaker": bookmaker,
                "status": "TIMEOUT",
                "final_url": page.url,
                "matches": [],
            }
        except Exception as exc:
            log(
                f"[{bookmaker}] homepage error: {exc} | "
                f"elapsed={time.monotonic() - bookmaker_started:.1f}s"
            )
            return {
                "bookmaker": bookmaker,
                "status": "ERROR",
                "final_url": page.url,
                "matches": [],
            }

        http_status = response.status if response else 0
        final_url = page.url

        # V3.20 FAST-FAIL: do not spend the remaining timeout on pages that
        # are already known to be blocked or unusable. This is deliberately
        # conservative: anything not explicitly rejected continues to the
        # strict event-window verifier.
        if fast_http_rejection_status(http_status):
            status = "CAPTCHA" if http_status in {403, 429, 451} else "HTTP_ERROR"
            log(
                f"[{bookmaker}] FAST-FAIL HTTP={http_status} "
                f"final={final_url} -> {status}"
            )
            return {
                "bookmaker": bookmaker,
                "status": status,
                "final_url": final_url,
                "matches": [],
            }

        if fast_block_url(final_url):
            log(
                f"[{bookmaker}] FAST-FAIL blocked URL "
                f"final={final_url}"
            )
            return {
                "bookmaker": bookmaker,
                "status": "CAPTCHA",
                "final_url": final_url,
                "matches": [],
            }

        title = await page.title()
        body_text = await safe_body_text(page)

        log(
            f"[{bookmaker}] HTTP={http_status} "
            f"final={final_url} text={len(body_text)}"
        )

        # HTTP 200 with no rendered text is not confirmation. Never continue
        # into searches for an empty document.
        if not body_text:
            log(f"[{bookmaker}] FAST-FAIL empty body -> NOT_CONFIRMED")
            return {
                "bookmaker": bookmaker,
                "status": "NOT_CONFIRMED",
                "final_url": final_url,
                "matches": [],
            }

        if protection_detected(title, body_text, final_url):
            log(f"[{bookmaker}] CAPTCHA/Cloudflare -> SKIP")
            return {
                "bookmaker": bookmaker,
                "status": "CAPTCHA",
                "final_url": page.url,
                "matches": [],
            }

        all_confirmed = []

        for match in matches:
            if timed_out():
                return {
                    "bookmaker": bookmaker,
                    "status": "HARD_TIMEOUT",
                    "final_url": page.url if page else homepage_url,
                    "matches": [],
                }

            verification = await verify_page_for_match(
                page, match, bookmaker
            )

            if verification["status"] == "CAPTCHA":
                return {
                    "bookmaker": bookmaker,
                    "status": "CAPTCHA",
                    "final_url": page.url,
                    "matches": [],
                }

            for found in verification.get("matches", []):
                found["match"] = match
                all_confirmed.append(found)

            if verification.get("matches"):
                continue

            candidate_links = await collect_candidate_links(
                page, page.url, match
            )

            checked_links = set()

            for candidate_url in candidate_links[:MAX_CANDIDATE_PAGES_PER_MATCH]:
                if timed_out():
                    return {
                        "bookmaker": bookmaker,
                        "status": "HARD_TIMEOUT",
                        "final_url": page.url if page else homepage_url,
                        "matches": [],
                    }
                if candidate_url in checked_links:
                    continue
                checked_links.add(candidate_url)

                try:
                    await page.goto(
                        candidate_url,
                        wait_until="domcontentloaded",
                        timeout=goto_timeout_ms(),
                    )
                    wait_ms = min(1500, BROWSER_WAIT_MS, max(0, _deadline_remaining_ms(deadline) - 250))
                    if wait_ms > 0:
                        await page.wait_for_timeout(wait_ms)
                except Exception:
                    continue

                title = await page.title()
                body_text = await safe_body_text(page)

                if protection_detected(title, body_text, page.url):
                    log(f"[{bookmaker}] protected event page -> skip")
                    continue

                verification = await verify_page_for_match(
                    page, match, bookmaker
                )

                for found in verification.get("matches", []):
                    found["match"] = match
                    if not found.get("href"):
                        found["href"] = page.url
                    all_confirmed.append(found)

                if verification.get("matches"):
                    break

            if any(x.get("match") == match for x in all_confirmed):
                continue

            if timed_out():
                return {
                    "bookmaker": bookmaker,
                    "status": "HARD_TIMEOUT",
                    "final_url": page.url if page else homepage_url,
                    "matches": [],
                }
            try:
                await page.goto(
                    homepage_url,
                    wait_until="domcontentloaded",
                    timeout=goto_timeout_ms(),
                )
                wait_ms = min(1200, BROWSER_WAIT_MS, max(0, _deadline_remaining_ms(deadline) - 250))
                if wait_ms > 0:
                    await page.wait_for_timeout(wait_ms)
            except Exception:
                continue

            search_result = await internal_search(
                page, bookmaker, match, homepage_url, deadline=deadline
            )
            if search_result["status"] == "HARD_TIMEOUT":
                return {
                    "bookmaker": bookmaker,
                    "status": "HARD_TIMEOUT",
                    "final_url": page.url if page else homepage_url,
                    "matches": [],
                }

            if search_result["status"] == "CAPTCHA":
                continue

            for search_url in search_result.get("links", [])[:MAX_SEARCH_LINKS]:
                if timed_out():
                    return {
                        "bookmaker": bookmaker,
                        "status": "HARD_TIMEOUT",
                        "final_url": page.url if page else homepage_url,
                        "matches": [],
                    }
                try:
                    await page.goto(
                        search_url,
                        wait_until="domcontentloaded",
                        timeout=goto_timeout_ms(),
                    )
                    wait_ms = min(1500, BROWSER_WAIT_MS, max(0, _deadline_remaining_ms(deadline) - 250))
                    if wait_ms > 0:
                        await page.wait_for_timeout(wait_ms)
                except Exception:
                    continue

                title = await page.title()
                body_text = await safe_body_text(page)

                if protection_detected(title, body_text, page.url):
                    continue

                verification = await verify_page_for_match(
                    page, match, bookmaker
                )

                for found in verification.get("matches", []):
                    found["match"] = match
                    if not found.get("href"):
                        found["href"] = page.url
                    all_confirmed.append(found)

                if verification.get("matches"):
                    break

            # Free-mode hygiene: release the document/page between matches.
            if match is not matches[-1]:
                try:
                    await page.close(run_before_unload=False)
                except Exception:
                    pass
                page = await context.new_page()
                page.set_default_timeout(4000)
                page.set_default_navigation_timeout(min(BROWSER_TIMEOUT_MS, 8000))

        unique = {}
        for found in all_confirmed:
            match = found["match"]
            key = (
                match["home_norm"],
                match["away_norm"],
                match["phase"],
                found.get("href", ""),
            )
            unique[key] = found

        confirmed = list(unique.values())
        status = "CONFIRMED" if confirmed else "NOT_CONFIRMED"

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
                await page.close(run_before_unload=False)
        except Exception as exc:
            log(f"[{bookmaker}] page close warning: {exc}")

        try:
            if context:
                await context.close()
        except Exception as exc:
            log(f"[{bookmaker}] context close warning: {exc}")

        try:
            if browser:
                await browser.close()
        except Exception as exc:
            log(f"[{bookmaker}] browser close warning: {exc}")

        try:
            if playwright:
                await playwright.stop()
        except Exception as exc:
            log(f"[{bookmaker}] Playwright shutdown warning: {exc}")

        # Drop large Playwright/page references and ask Python to reclaim
        # cyclic objects before the next bookmaker starts.
        page = None
        context = None
        browser = None
        playwright = None
        gc.collect()
        log_memory(f"{bookmaker} after cleanup")

        log(
            f"[{bookmaker}] CLEANUP complete | "
            f"cleanup={time.monotonic() - cleanup_started:.2f}s | "
            f"total={time.monotonic() - bookmaker_started:.1f}s"
        )


def browser_check_one(bookmaker, homepage_url, matches):
    """Run one bookmaker scan in a single async loop.

    Timeout enforcement is deadline-based inside Playwright, so the coroutine
    is not cancelled from another thread. This avoids orphaned Playwright
    futures and TargetClosedError noise during cleanup.
    """
    import asyncio
    return asyncio.run(
        browser_check_one_async(
            bookmaker,
            homepage_url,
            matches,
        )
    )


# ============================================================
# BOOKMAKER SCAN
# ============================================================

def select_bookmaker_batch():
    global bookmaker_rotation_index

    if not BOOKMAKERS:
        return []

    if not FREE_MODE or FREE_BOOKMAKER_BATCH_SIZE >= len(BOOKMAKERS):
        return list(BOOKMAKERS)

    with bookmaker_rotation_lock:
        start = bookmaker_rotation_index % len(BOOKMAKERS)
        selected = []
        for offset in range(min(FREE_BOOKMAKER_BATCH_SIZE, len(BOOKMAKERS))):
            selected.append(BOOKMAKERS[(start + offset) % len(BOOKMAKERS)])
        bookmaker_rotation_index = (start + len(selected)) % len(BOOKMAKERS)
        return selected


def scan_bookmakers(matches):
    results = []

    if not matches:
        return results

    selected_bookmakers = select_bookmaker_batch()
    worker_count = 1  # Free profile: never allow browser concurrency.

    bookmakers_started = time.monotonic()
    gc.collect()
    log_memory("before bookmaker scan")

    log(
        f"[BOOKMAKERS] START | total_sites={len(BOOKMAKERS)} "
        f"batch={len(selected_bookmakers)} workers={worker_count} "
        f"matches={len(matches)} free_mode={FREE_MODE}"
    )
    update_scanner_state(phase="BOOKMAKERS", last_error=None)

    for bookmaker, url in selected_bookmakers:
        if FREE_MODE and memory_guarded(FREE_MEMORY_GUARD_MB):
            results.append({
                "bookmaker": bookmaker,
                "status": "MEMORY_GUARD",
                "final_url": url,
                "matches": [],
            })
            log(f"[BOOKMAKERS] MEMORY_GUARD -> skipping remaining site: {bookmaker}")
            break

        try:
            result = browser_check_one(bookmaker, url, matches)
            results.append(result)
            log(
                f"[BOOKMAKERS] DONE | {bookmaker} | "
                f"status={result.get('status')} | "
                f"confirmed={len(result.get('matches', []))}"
            )
        except Exception as exc:
            log(f"[BOOKMAKERS] {bookmaker} worker error: {exc}")
            results.append({
                "bookmaker": bookmaker,
                "status": "ERROR",
                "final_url": "",
                "matches": [],
            })

        gc.collect()
        if FREE_MODE:
            # Give Chromium's child process a short window to exit before
            # another browser is launched.
            time.sleep(0.5)
            if memory_guarded(FREE_MEMORY_GUARD_MB):
                log("[BOOKMAKERS] Memory guard after cleanup -> stop this cycle")
                break

    gc.collect()
    log_memory("after bookmaker scan")
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
        "[START] V3.20 overlap protection=ENABLED"
    )
    log(
        "[START] V3.20 Chromium launch serialization=ENABLED"
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
    log("[START] Playwright API=ASYNC (safe for asyncio and Render)")
    log("[START] V3.20 fast-fail=HTTP 401/403/429/451 + blocked URLs + empty body")
    log(f"[START] HTTP_TIMEOUT={HTTP_TIMEOUT}s | BROWSER_TIMEOUT_MS={BROWSER_TIMEOUT_MS} | BROWSER_WAIT_MS={BROWSER_WAIT_MS}ms")
    log("[START] Health endpoint: /health")
    log(f"[START] FREE_MODE={FREE_MODE} | memory_guard={FREE_MEMORY_GUARD_MB:.0f}MB | batch={FREE_BOOKMAKER_BATCH_SIZE} | bookmaker_timeout={FREE_BOOKMAKER_HARD_TIMEOUT_SECONDS}s | kooora_timeout={KOOORA_HARD_TIMEOUT_SECONDS}s")
    log(f"[START] discovery_links={MAX_DISCOVERY_LINKS} | candidate_pages={MAX_CANDIDATE_PAGES_PER_MATCH} | search_variants={MAX_SEARCH_VARIANTS} | search_inputs={MAX_SEARCH_INPUTS}")

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

            # V3.10 hard guard:
            # If a previous scan is still running, do NOT start another
            # scan and therefore do NOT start any additional Chromium.
            acquired = scan_lock.acquire(
                blocking=False
            )

            if not acquired:
                log(
                    "[SCAN] Previous scan still running -> "
                    "SKIP this cycle | no Chromium started"
                )

            else:
                try:
                    log(
                        "[SCAN] Scan lock acquired -> "
                        "starting one protected scan"
                    )
                    process_scan()

                finally:
                    scan_lock.release()
                    log(
                        "[SCAN] Scan lock released -> "
                        "Chromium/bookmaker phase may start on next cycle"
                    )

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

    # V3.12: no Telegram startup diagnostic. A restart must not create
    # noise or consume Telegram requests; real alerts remain unchanged.
    log("[MAIN] V3.20 startup diagnostic Telegram disabled")

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
