import os
import json
import time
import logging
import re
from datetime import datetime, date, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List

import pytz
from bs4 import BeautifulSoup

# Playwright used for fetching (bypasses Cloudflare WAF).
# Falls back gracefully if playwright is not installed.
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False

# ============================================================
# CONFIRMED SUNRISE ZONES - Data Acquisition Service
# Authoritative source: timeanddate.com
# Returns ONLY confirmed past sunrises.
# Never returns future or predicted sunrise times.
# ============================================================

CITY_CONFIGS = {
    "tokyo": {
        "slug": "japan/tokyo", "tz": "Asia/Tokyo",
        "lat": 35.6895, "lon": 139.6917, "elevation": 40,
        "source_url_base": "https://www.timeanddate.com/sun/japan/tokyo",
    },
    "london": {
        "slug": "uk/london", "tz": "Europe/London",
        "lat": 51.5085, "lon": -0.1257, "elevation": 25,
        "source_url_base": "https://www.timeanddate.com/sun/uk/london",
    },
    "newyork": {
        "slug": "usa/new-york", "tz": "America/New_York",
        "lat": 40.7143, "lon": -74.0060, "elevation": 10,
        "source_url_base": "https://www.timeanddate.com/sun/usa/new-york",
    },
}

CACHE_FILE = os.path.join("cache", "sunrise_cache.json")
LOG_FILE   = os.path.join("logs",  "fetch_log.jsonl")


@dataclass
class SunriseRecord:
    city: str
    local_date: str               # YYYY-MM-DD (local city date)
    local_sunrise: str            # HH:MM:SS or HH:MM
    local_sunrise_hh: int
    local_sunrise_mm: int
    local_sunrise_ss: int
    has_seconds: bool             # True if seconds were available from source
    iana_timezone: str
    utc_timestamp_ms: int         # UTC ms of sunrise event
    candle_open_utc_ms: int       # UTC ms of 1-min candle open (floor to min)
    source: str                   # "timeanddate.com"
    source_url: str               # exact URL used
    confirmation_status: str      # CONFIRMED | PENDING | UNAVAILABLE
    fetched_at: str               # ISO 8601 UTC


def _setup_logging():
    os.makedirs("logs", exist_ok=True)
    log = logging.getLogger("sunrise_fetcher")
    log.setLevel(logging.DEBUG)
    log.propagate = False  # prevent double-logging when root logger also has handlers
    if not log.handlers:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        log.addHandler(ch)
    return log


logger = _setup_logging()


# ── Cache ──────────────────────────────────────────────────
def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Cache load failed: %s", e)
    return {}


def save_cache(cache):
    os.makedirs("cache", exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


# ── Future-date protection ─────────────────────────────────
def is_confirmed(record) -> bool:
    """Returns True ONLY if the sunrise event has already occurred."""
    now_ms = int(time.time() * 1000)
    return record.utc_timestamp_ms < now_ms


# ── Playwright HTTP fetch (bypasses Cloudflare) ────────────
_PLAYWRIGHT_INSTANCE = None
_PLAYWRIGHT_BROWSER  = None


def _get_playwright_html(url: str, retries: int = 3) -> Optional[str]:
    """
    Fetch a URL using a persistent Playwright/Chromium browser session.
    Uses domcontentloaded (not networkidle) to avoid Cloudflare JS loop timeout.
    Returns HTML string or None on failure.
    """
    global _PLAYWRIGHT_INSTANCE, _PLAYWRIGHT_BROWSER

    if not _HAS_PLAYWRIGHT:
        logger.critical("playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        return None

    for attempt in range(1, retries + 1):
        try:
            # Lazy-init: reuse browser session across all fetches in one run
            if _PLAYWRIGHT_BROWSER is None:
                _PLAYWRIGHT_INSTANCE = sync_playwright().start()
                _PLAYWRIGHT_BROWSER = _PLAYWRIGHT_INSTANCE.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
                logger.info("Playwright Chromium browser started")

            context = _PLAYWRIGHT_BROWSER.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="UTC",
            )
            page = context.new_page()
            time.sleep(1.5)  # polite rate-limiting

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except PWTimeout:
                # domcontentloaded timed out — grab whatever loaded so far
                logger.warning("domcontentloaded timeout for %s (attempt %d), reading partial content", url, attempt)

            html = page.content()
            context.close()

            if "as-monthsun" in html or "sunrise" in html.lower():
                logger.info("Fetched %d bytes from %s", len(html), url)
                return html
            else:
                logger.warning("Page loaded but no sunrise data found (attempt %d): %s", attempt, url)

        except Exception as exc:
            logger.error("Playwright fetch error (attempt %d): %s — %s", attempt, url, exc)
            # Reset browser on error
            _close_playwright()

        if attempt < retries:
            time.sleep(3.0 * attempt)

    logger.critical("All %d attempts failed for %s", retries, url)
    return None


def _close_playwright():
    """Close the persistent browser session."""
    global _PLAYWRIGHT_INSTANCE, _PLAYWRIGHT_BROWSER
    try:
        if _PLAYWRIGHT_BROWSER:
            _PLAYWRIGHT_BROWSER.close()
        if _PLAYWRIGHT_INSTANCE:
            _PLAYWRIGHT_INSTANCE.stop()
    except Exception:
        pass
    _PLAYWRIGHT_BROWSER  = None
    _PLAYWRIGHT_INSTANCE = None


# ── HTML Parsing ───────────────────────────────────────────
def _parse_time_str(raw):
    """Parse timeanddate sunrise string to (hh, mm, ss, has_seconds) or None."""
    raw = re.split(r"[\u2191\u2193(]", raw)[0].strip()
    # HH:MM:SS am/pm
    m = re.fullmatch(r"(\d{1,2}):(\d{2}):(\d{2})\s*(am|pm)", raw, re.IGNORECASE)
    if m:
        hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if m.group(4).lower() == "pm" and hh != 12: hh += 12
        elif m.group(4).lower() == "am" and hh == 12: hh = 0
        return hh, mm, ss, True
    # HH:MM:SS 24h
    m = re.fullmatch(r"(\d{1,2}):(\d{2}):(\d{2})", raw)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), True
    # HH:MM am/pm
    m = re.fullmatch(r"(\d{1,2}):(\d{2})\s*(am|pm)", raw, re.IGNORECASE)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if m.group(3).lower() == "pm" and hh != 12: hh += 12
        elif m.group(3).lower() == "am" and hh == 12: hh = 0
        return hh, mm, 0, False
    # HH:MM 24h
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if hh > 23 or mm > 59:
            return None
        return hh, mm, 0, False
    return None


def _parse_daily_page(html):
    """Parse main daily sun page. Returns (hh, mm, ss, has_sec) or None."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator=" ")
    m = re.search(
        r"[Ss]unrise[^\n]{0,80}?(\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?)",
        text, re.IGNORECASE
    )
    if m:
        return _parse_time_str(m.group(1).strip())
    return None


def _parse_monthly_table(html, day):
    """Parse monthly table (minute precision). Returns (hh, mm, ss, has_sec) or None."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="as-monthsun")
    if not table:
        logger.critical("HTML STRUCTURE CHANGED: table#as-monthsun not found. Manual fix required.")
        return None
    tbody = table.find("tbody")
    if not tbody:
        logger.critical("HTML STRUCTURE CHANGED: no tbody in as-monthsun")
        return None
    for row in tbody.find_all("tr"):
        day_attr = row.get("data-day")
        if day_attr and int(day_attr) == day:
            tds = row.find_all("td")
            if not tds:
                return None
            raw = tds[0].get_text(separator=" ", strip=True)
            result = _parse_time_str(raw)
            if not result:
                logger.error("Could not parse sunrise time: %r", raw)
            return result
    logger.error("Day %d not found in monthly table", day)
    return None


# ── UTC Timestamp Computation ──────────────────────────────
def _compute_timestamps(tz_str, yr, mo, dy, hh, mm, ss):
    """Compute UTC timestamps with proper DST handling via pytz."""
    tz = pytz.timezone(tz_str)
    local_dt = tz.localize(datetime(yr, mo, dy, hh, mm, ss), is_dst=None)
    utc_dt = local_dt.astimezone(pytz.utc)
    utc_ms = int(utc_dt.timestamp() * 1000)
    candle_open = utc_dt.replace(second=0, microsecond=0)
    candle_ms = int(candle_open.timestamp() * 1000)
    return utc_ms, candle_ms


# ── Core Fetch ─────────────────────────────────────────────
def fetch_sunrise(city_key, target_date):
    """
    Fetch confirmed sunrise for a city on a date.
    Returns SunriseRecord or None.
    NEVER invents or approximates data.
    """
    if city_key not in CITY_CONFIGS:
        logger.error("Invalid city key: %r", city_key)
        return None

    cfg = CITY_CONFIGS[city_key]
    date_str = target_date.strftime("%Y-%m-%d")

    # Cache lookup
    cache = load_cache()
    cache_key = "%s_%s" % (city_key, date_str)
    if cache_key in cache:
        logger.info("Cache hit: %s", cache_key)
        rec = SunriseRecord(**cache[cache_key])
        if rec.confirmation_status != "CONFIRMED" and is_confirmed(rec):
            rec.confirmation_status = "CONFIRMED"
            cache[cache_key] = asdict(rec)
            save_cache(cache)
        return rec if rec.confirmation_status == "CONFIRMED" else None

    today = datetime.utcnow().date()
    parsed = None
    source_url = ""

    if target_date == today:
        # Daily page: may have seconds precision
        source_url = cfg["source_url_base"]
        logger.info("Fetching daily page: %s", source_url)
        html = _get_playwright_html(source_url)
        if html:
            parsed = _parse_daily_page(html)
        if not parsed:
            logger.warning("Daily page parse failed; falling back to monthly table")

    if not parsed:
        source_url = "%s?month=%d&year=%d" % (cfg["source_url_base"], target_date.month, target_date.year)
        logger.info("Fetching monthly table: %s", source_url)
        html = _get_playwright_html(source_url)
        if not html:
            logger.error("timeanddate.com unreachable for %s %s -- no data invented", city_key, date_str)
            return None
        parsed = _parse_monthly_table(html, target_date.day)

    if not parsed:
        logger.error("Failed to parse sunrise for %s %s", city_key, date_str)
        return None

    hh, mm, ss, has_sec = parsed

    if not (3 <= hh <= 9):
        logger.error("Sunrise hour %d outside valid range (03-09) for %s on %s", hh, city_key, date_str)
        return None

    try:
        utc_ms, candle_ms = _compute_timestamps(cfg["tz"], target_date.year, target_date.month, target_date.day, hh, mm, ss)
    except Exception as exc:
        logger.error("Timestamp computation failed for %s %s: %s", city_key, date_str, exc)
        return None

    local_sunrise_str = ("%02d:%02d:%02d" % (hh, mm, ss)) if has_sec else ("%02d:%02d" % (hh, mm))
    record = SunriseRecord(
        city=city_key,
        local_date=date_str,
        local_sunrise=local_sunrise_str,
        local_sunrise_hh=hh,
        local_sunrise_mm=mm,
        local_sunrise_ss=ss,
        has_seconds=has_sec,
        iana_timezone=cfg["tz"],
        utc_timestamp_ms=utc_ms,
        candle_open_utc_ms=candle_ms,
        source="timeanddate.com",
        source_url=source_url,
        confirmation_status="PENDING",
        fetched_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    if not is_confirmed(record):
        logger.info("Sunrise %s %s has not yet occurred -- skipping", city_key, date_str)
        return None

    record.confirmation_status = "CONFIRMED"
    cache[cache_key] = asdict(record)
    save_cache(cache)
    logger.info("CONFIRMED: %s %s sunrise %s (candle UTC ms: %d)", city_key, date_str, local_sunrise_str, candle_ms)
    return record


def fetch_all_cities(target_date):
    """Fetch all 3 cities for a given date."""
    return {city: fetch_sunrise(city, target_date) for city in CITY_CONFIGS}


def fetch_rolling_window(days=12):
    """Fetch confirmed sunrise records for the last N calendar days."""
    records = []
    today = datetime.utcnow().date()
    try:
        for i in range(days):
            target = today - timedelta(days=i)
            for city_key in CITY_CONFIGS:
                rec = fetch_sunrise(city_key, target)
                if rec is not None:
                    records.append(rec)
    finally:
        _close_playwright()  # always close browser cleanly
    return records
