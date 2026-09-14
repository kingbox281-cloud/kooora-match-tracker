import os
import re
import time
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from flask import Flask

# =========================================================
# SETTINGS
# =========================================================

SCAN_INTERVAL = 60
KOOORA_TIMEOUT = 20
BOOKMAKER_TIMEOUT = 10
MAX_BOOKMAKER_WORKERS = 6

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

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram token/chat ID is not configured.", flush=True)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=15,
        )
        print(f"Telegram response: HTTP {response.status_code}", flush=True)
        return response.ok
    except requests.RequestException as exc:
        print(f"Telegram error: {exc}", flush=True)
        return False


# =========================================================
# HTTP SESSION / HEADERS
# =========================================================

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)

KOOORA_URL = (
    "https://www.kooora.com/"
    "%D9%83%D8%B1%D8%A9-%D8%A7%D9%84%D9%82%D8%AF%D9%85/"
    "%D9%85%D8%A8%D8%A7%D8%B1%D9%8A%D8%A7%D8%AA-%D8%A7%D9%84%D9%8A%D9%88%D9%85"
)
KOOORA_FALLBACK_URL = "https://www.kooora.com/default.aspx?g=matches"

KOOORA_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ar,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://www.kooora.com/",
}

# =========================================================
# BOOKMAKERS
# =========================================================

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

TARGET_BOOKMAKERS = list(BOOKMAKER_URLS.keys())

CAPTCHA_WORDS = (
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
)

PREMATCH_MARKERS = (
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
    "nicht begonnen",
    "noch nicht gestartet",
    "bevorstehend",
    "spielbeginn",
    "لم تبدأ",
    "لم تبدأ بعد",
    "قبل المباراة",
    "قبل بداية المباراة",
    "قبل البداية",
    "لم تبدأ المباراة",
)

POSTMATCH_MARKERS = (
    "finished",
    "full time",
    "final",
    "ended",
    "completed",
    "beendet",
    "endstand",
    "abgeschlossen",
    "انتهت",
    "النهاية",
    "نهاية المباراة",
    "مكتملة",
)

# =========================================================
# TEXT / MATCH HELPERS
# =========================================================


def clean_text(text):
    if not text:
        return ""
    text = str(text).replace("\xa0", " ").replace("\\u00a0", " ")
    text = text.replace("\\/", "/")
    text = text.translate(str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789",
    ))
    return re.sub(r"\s+", " ", text).strip()


def normalize_match_text(text):
    text = clean_text(text).lower()
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    text = (text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
                .replace("ى", "ي").replace("ة", "ه").replace("ـ", ""))
    text = re.sub(r"[|/\\:;,.()\[\]{}\-_–—]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def team_tokens(team):
    ignored = {
        "fc", "cf", "sc", "afc", "fk", "sv", "sk", "ac", "ks", "nk",
        "bk", "cd", "ud", "rc", "ca", "ss", "as", "1", "2",
    }
    return {
        token for token in normalize_match_text(team).split()
        if token not in ignored and len(token) >= 2
    }


def token_present(haystack, token):
    return re.search(rf"(?<![\w\u0600-\u06FF]){re.escape(token)}(?![\w\u0600-\u06FF])", haystack) is not None


def team_is_in_text(team, text):
    exact = normalize_match_text(team)
    haystack = normalize_match_text(text)
    if not exact or not haystack:
        return False

    # Strongest match: complete normalized team name as a word-safe phrase.
    if re.search(
        rf"(?<![\w\u0600-\u06FF]){re.escape(exact)}(?![\w\u0600-\u06FF])",
        haystack,
    ):
        return True

    tokens = team_tokens(team)
    if not tokens:
        return False

    present = sum(token_present(haystack, token) for token in tokens)
    if len(tokens) == 1:
        return present == 1
    if len(tokens) == 2:
        return present == 2
    return present >= max(2, (len(tokens) + 1) // 2)


def teams_match(container_text, team1, team2):
    if not team_is_in_text(team1, container_text):
        return False
    if not team_is_in_text(team2, container_text):
        return False
    return True


def has_prematch_marker(text):
    normalized = normalize_match_text(text)
    return any(normalize_match_text(marker) in normalized for marker in PREMATCH_MARKERS)


def has_postmatch_marker(text):
    normalized = normalize_match_text(text)
    return any(normalize_match_text(marker) in normalized for marker in POSTMATCH_MARKERS)


def detect_captcha(response):
    try:
        text = (response.text or "").lower()
    except Exception:
        text = ""
    return any(word in text for word in CAPTCHA_WORDS)

# =========================================================
# KOOORA PARSING
# =========================================================

FT_RE = re.compile(r"انتهت|إنتهت|النهاية|نهاية المباراة|\bFT\b|FULL[\s_-]*TIME", re.I)
HT_RE = re.compile(r"استراحة|نهاية الشوط|الشوط الأول|الشوط الاول|بين الشوطين|\bHT\b|HALF[\s_-]*TIME", re.I)
SINGLE_SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")


def extract_competition_context(match_element):
    result = {"country": "الدولي / محلي", "league": "الدوري العام", "round": None}
    parent = match_element.parent
    section = None

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

    for country in sorted(countries, key=len, reverse=True):
        if country in prefix:
            result["country"] = country
            league = prefix.replace(country, "").strip()
            if league:
                result["league"] = league
            return result

    if prefix:
        result["league"] = prefix
    return result


def parse_kooora_match_element(match_element):
    data_status = str(match_element.get("data-match-status", "")).upper().strip()
    if data_status not in {"RESULT", "LIVE"}:
        return None

    status_element = match_element.select_one(".fco-match-status")
    status_text = clean_text(status_element.get_text(" ", strip=True) if status_element else "")

    if data_status == "RESULT":
        status = "FT"
    elif HT_RE.search(status_text):
        status = "HT"
    else:
        return None

    basic = match_element.select_one(".fco-match-basic-data")
    if basic is None:
        return None
    basic_text = clean_text(basic.get_text(" ", strip=True))
    numbers = list(SINGLE_SCORE_RE.finditer(basic_text))
    if len(numbers) < 2:
        return None

    first, second = numbers[0], numbers[1]
    try:
        score1, score2 = int(first.group(1)), int(second.group(1))
    except ValueError:
        return None

    team1 = basic_text[:first.start()].strip()
    team2 = basic_text[first.end():second.start()].strip()

    team1 = re.sub(r"\s+\b[A-Z]{2,5}\b\s*$", "", team1).strip()
    team2 = re.sub(r"\s+\b[A-Z]{2,5}\b\s*$", "", team2).strip()
    team1 = clean_text(FT_RE.sub(" ", HT_RE.sub(" ", team1)))
    team2 = clean_text(FT_RE.sub(" ", HT_RE.sub(" ", team2)))

    if not team1 or not team2 or normalize_match_text(team1) == normalize_match_text(team2):
        return None

    link = match_element.select_one("a.fco-match-data")
    href = str(link.get("href", "")).strip() if link else ""
    context = extract_competition_context(match_element)

    return {
        "match_key": href or f"{normalize_match_text(team1)}|{normalize_match_text(team2)}",
        "match_name": f"{team1} vs {team2}",
        "team1": team1,
        "team2": team2,
        "score": (score1, score2),
        "status": status,
        "country": context["country"],
        "league": context["league"],
        "round": context["round"],
    }


def find_kooora_matches(soup):
    items = soup.select(".fco-match-list-item[data-match-status]")
    all_today = []
    alert_matches = []
    seen = set()

    for item in items:
        data_status = str(item.get("data-match-status", "")).upper().strip()
        basic = item.select_one(".fco-match-basic-data")
        if basic is None:
            continue
        raw_basic = clean_text(basic.get_text(" ", strip=True))
        href_element = item.select_one("a.fco-match-data")
        href = str(href_element.get("href", "")).strip() if href_element else ""
        card_key = href or raw_basic
        if card_key in seen:
            continue
        seen.add(card_key)
        all_today.append({"key": card_key, "data_status": data_status, "raw": raw_basic})

        parsed = parse_kooora_match_element(item)
        if parsed:
            alert_matches.append(parsed)

    return all_today, alert_matches


def get_kooora_page():
    for url in (KOOORA_URL, KOOORA_FALLBACK_URL):
        try:
            response = requests.get(url, headers=KOOORA_HEADERS, timeout=KOOORA_TIMEOUT, allow_redirects=True)
            print(f"Kooora response: HTTP {response.status_code} - {url}", flush=True)
            print(f"Kooora final URL: {response.url}", flush=True)
            print(f"Kooora HTML length: {len(response.text)}", flush=True)
            if response.ok and response.text:
                return response
        except requests.RequestException as exc:
            print(f"Kooora connection error: {exc}", flush=True)
    return None

# =========================================================
# BOOKMAKER CHECK
# =========================================================

BOOKMAKER_SELECTORS = (
    "article", "li", "tr",
    "[class*='event']", "[class*='match']", "[class*='fixture']",
    "[class*='game']", "[class*='sport']",
    "[data-event-id]", "[data-event]", "[data-fixture-id]", "[data-match-id]",
)


def inspect_bookmaker_html(bookmaker, response, team1, team2):
    if detect_captcha(response):
        return {"status": "CAPTCHA", "url": response.url, "evidence": ""}
    if response.status_code in (401, 403, 429):
        return {"status": "BLOCKED", "url": response.url, "evidence": ""}
    if response.status_code >= 500:
        return {"status": "SERVER_ERROR", "url": response.url, "evidence": ""}
    if response.status_code != 200:
        return {"status": "NOT_CHECKED", "url": response.url, "evidence": ""}

    soup = BeautifulSoup(response.text, "html.parser")
    candidates = []
    seen_ids = set()

    for selector in BOOKMAKER_SELECTORS:
        try:
            elements = soup.select(selector)
        except Exception:
            continue
        for element in elements:
            if id(element) in seen_ids:
                continue
            seen_ids.add(id(element))
            text = clean_text(element.get_text(" ", strip=True))
            if not text or len(text) > 2500:
                continue
            if teams_match(text, team1, team2):
                candidates.append(text)

    candidates.sort(key=len)
    for text in candidates:
        if has_postmatch_marker(text):
            continue
        if has_prematch_marker(text):
            return {"status": "SAME_MATCH_PREMATCH", "url": response.url, "evidence": text[:500]}

    # Simple bookmaker pages may put both teams directly in a link.
    for link in soup.find_all("a"):
        text = clean_text(link.get_text(" ", strip=True))
        if text and len(text) <= 1200 and teams_match(text, team1, team2):
            if not has_postmatch_marker(text) and has_prematch_marker(text):
                return {"status": "SAME_MATCH_PREMATCH", "url": response.url, "evidence": text[:500]}

    return {"status": "NOT_CONFIRMED", "url": response.url, "evidence": ""}


def check_bookmaker_match(bookmaker, team1, team2):
    url = BOOKMAKER_URLS[bookmaker]
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": url,
    }
    try:
        response = requests.get(url, headers=headers, timeout=BOOKMAKER_TIMEOUT, allow_redirects=True)
        result = inspect_bookmaker_html(bookmaker, response, team1, team2)
        print(f"{bookmaker}: HTTP {response.status_code} {result['status']} {response.url}", flush=True)
        if result["status"] == "SAME_MATCH_PREMATCH":
            print(f"🚨 SAME MATCH PRE-MATCH: {bookmaker} | {team1} vs {team2}", flush=True)
        return result
    except requests.Timeout:
        print(f"{bookmaker}: timeout", flush=True)
        return {"status": "TIMEOUT", "url": url, "evidence": ""}
    except requests.RequestException as exc:
        print(f"{bookmaker}: {exc}", flush=True)
        return {"status": "ERROR", "url": url, "evidence": ""}
    except Exception as exc:
        print(f"{bookmaker}: unexpected error: {exc}", flush=True)
        return {"status": "ERROR", "url": url, "evidence": ""}


def check_all_bookmakers_for_match(team1, team2):
    results = {}
    # Parallel requests keep one 60-second cycle from becoming unnecessarily long.
    with ThreadPoolExecutor(max_workers=MAX_BOOKMAKER_WORKERS) as executor:
        futures = {
            executor.submit(check_bookmaker_match, bookmaker, team1, team2): bookmaker
            for bookmaker in TARGET_BOOKMAKERS
        }
        for future in as_completed(futures):
            bookmaker = futures[future]
            try:
                results[bookmaker] = future.result()
            except Exception as exc:
                print(f"{bookmaker}: worker error: {exc}", flush=True)
                results[bookmaker] = {"status": "ERROR", "url": BOOKMAKER_URLS[bookmaker], "evidence": ""}
    return results

# =========================================================
# ALERTS
# =========================================================

sent_alerts = set()


def format_and_send_alert(match):
    print(f"🔎 Checking SAME MATCH on bookmakers: {match['match_name']}", flush=True)
    results = check_all_bookmakers_for_match(match["team1"], match["team2"])
    confirmed = [
        bookmaker for bookmaker in TARGET_BOOKMAKERS
        if results.get(bookmaker, {}).get("status") == "SAME_MATCH_PREMATCH"
    ]

    if not confirmed:
        print(f"ℹ️ No SAME_MATCH_PREMATCH confirmation for {match['match_name']}", flush=True)
        return False

    now = datetime.now().strftime("%H:%M:%S")
    status_text = "انتهت المباراة تماماً (FT) ✅" if match["status"] == "FT" else "انتهى الشوط الأول (HT) ⏸️"
    title = "🚨 تنبيه: نفس المباراة ما زالت Pre-match"

    message = (
        f"{title}\n\n"
        f"⚽ المباراة: {match['match_name']}\n"
        f"🔢 النتيجة على كووورة: {match['score'][0]} - {match['score'][1]}\n"
        f"🌍 الدولة: {match['country']}\n"
        f"🏆 البطولة: {match['league']}"
    )
    if match.get("round"):
        message += f" — {match['round']}"
    message += (
        f"\n⏰ وقت التحديث: {now}\n"
        f"🛑 حالة كووورة: {status_text}\n\n"
        "🚨 نفس المباراة ما زالت Pre-match في:\n"
        + "".join(f"• {bookmaker}\n" for bookmaker in confirmed)
        + "\n⚠️ تم التأكد من وجود الفريقين داخل نفس عنصر المباراة مع علامة Pre-match.\n"
        "ℹ️ إذا كانت المنصة تستخدم JavaScript ولا تُظهر المباراة في HTML، فلن يتم اعتبارها مؤكدة."
    )
    return send_telegram_message(message)


def process_kooora_alerts(alert_matches):
    date_key = datetime.now().strftime("%Y-%m-%d")
    alerts = 0

    for match in alert_matches:
        alert_key = f"{date_key}|{match['match_key']}|{match['status']}"
        if alert_key in sent_alerts:
            continue

        print(
            f"🚨 REAL MATCH: {match['match_name']} | "
            f"{match['score'][0]}-{match['score'][1]} | {match['status']}",
            flush=True,
        )

        if format_and_send_alert(match):
            sent_alerts.add(alert_key)
            alerts += 1
        else:
            print("⏳ No bookmaker confirmation yet; retrying next cycle.", flush=True)

    return alerts

# =========================================================
# SCAN
# =========================================================


def check_kooora_matches():
    response = get_kooora_page()
    if response is None:
        print("❌ Unable to access Kooora", flush=True)
        return

    try:
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else "NO TITLE"
        print(f"Kooora title: {title[:200]}", flush=True)

        all_matches, alert_matches = find_kooora_matches(soup)
        fixture_count = sum(m["data_status"] == "FIXTURE" for m in all_matches)
        live_count = sum(m["data_status"] == "LIVE" for m in all_matches)
        result_count = sum(m["data_status"] == "RESULT" for m in all_matches)

        print(f"📅 TODAY cards: {len(all_matches)} | FIXTURE={fixture_count} | LIVE={live_count} | RESULT={result_count}", flush=True)
        print(f"⚽ HT/FT matches ready for bookmaker checking: {len(alert_matches)}", flush=True)

        for match in alert_matches:
            print(
                f"   REAL: {match['team1']} {match['score'][0]}-"
                f"{match['score'][1]} {match['team2']} [{match['status']}]",
                flush=True,
            )

        generated = process_kooora_alerts(alert_matches)
        print(f"✅ Kooora scan finished. New alerts: {generated}", flush=True)

        if len(sent_alerts) > 5000:
            sent_alerts.clear()
            print("sent_alerts cleared", flush=True)

    except Exception as exc:
        print(f"❌ Error scraping Kooora: {exc}", flush=True)

# =========================================================
# BOT LOOP
# =========================================================


def bot_loop():
    print("🚀 BOT LOOP STARTED", flush=True)
    send_telegram_message(
        "🚀 تم تشغيل بوت مراقبة كووورة بنجاح!\n\n"
        "📅 مراقبة جميع مباريات اليوم\n"
        "🟡 مراقبة HT\n"
        "🚨 مراقبة FT\n"
        "🛡️ منع أوقات المباريات الوهمية كأنها نتائج\n"
        "🚫 استبعاد CAPTCHA تلقائياً\n"
        "🔎 البحث عن نفس الفريقين داخل نفس مباراة المراهنات\n"
        "🔄 الفحص كل 60 ثانية"
    )

    while True:
        started = time.monotonic()
        try:
            print("\n==============================", flush=True)
            print("🔍 Checking ALL TODAY'S Kooora matches...", flush=True)
            check_kooora_matches()
            print("==============================\n", flush=True)
        except Exception as exc:
            print(f"❌ Bot loop error: {exc}", flush=True)

        elapsed = time.monotonic() - started
        sleep_for = max(1, SCAN_INTERVAL - elapsed)
        print(f"⏳ Next scan in {sleep_for:.0f} seconds...", flush=True)
        time.sleep(sleep_for)


# Start exactly one daemon thread in this process.
threading.Thread(target=bot_loop, daemon=True, name="kooora-bot").start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
