import pytest
import time
import pytz
from datetime import datetime, date, timedelta
from dataclasses import asdict
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sunrise_fetcher import (
    SunriseRecord, CITY_CONFIGS, is_confirmed,
    _parse_time_str, _parse_monthly_table, _compute_timestamps
)

# ============================================================
# FIXTURES
# ============================================================

def make_record(city="tokyo", date_str="2026-09-14",
                hh=5, mm=22, ss=37, has_sec=True,
                utc_offset_hours=9, future=False):
    """Helper: build a SunriseRecord with correct UTC timestamps."""
    tz_map = {"tokyo": "Asia/Tokyo", "london": "Europe/London", "newyork": "America/New_York"}
    iana = tz_map[city]
    yr, mo, dy = int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10])
    utc_ms, candle_ms = _compute_timestamps(iana, yr, mo, dy, hh, mm, ss)
    if future:
        utc_ms += 86400 * 1000  # push 1 day into future
        candle_ms += 86400 * 1000
    local_sunrise = f"{hh:02d}:{mm:02d}:{ss:02d}" if has_sec else f"{hh:02d}:{mm:02d}"
    return SunriseRecord(
        city=city,
        local_date=date_str,
        local_sunrise=local_sunrise,
        local_sunrise_hh=hh,
        local_sunrise_mm=mm,
        local_sunrise_ss=ss,
        has_seconds=has_sec,
        iana_timezone=iana,
        utc_timestamp_ms=utc_ms,
        candle_open_utc_ms=candle_ms,
        source="timeanddate.com",
        source_url=f"https://www.timeanddate.com/sun/{CITY_CONFIGS[city]['slug']}",
        confirmation_status="CONFIRMED" if not future else "PENDING",
        fetched_at="2026-09-14T06:00:00Z",
    )


@pytest.fixture
def tokyo_record():
    return make_record("tokyo", "2026-09-14", 5, 22, 37, True)

@pytest.fixture
def london_winter_record():
    return make_record("london", "2026-01-15", 7, 58, 0, False)

@pytest.fixture
def london_summer_record():
    return make_record("london", "2026-06-15", 4, 49, 0, False)

@pytest.fixture
def nyc_winter_record():
    return make_record("newyork", "2026-01-15", 7, 17, 0, False)

@pytest.fixture
def nyc_summer_record():
    return make_record("newyork", "2026-06-15", 5, 28, 0, False)

@pytest.fixture
def future_record():
    """A record whose sunrise hasn't occurred yet — must be rejected."""
    return make_record("tokyo", "2026-09-14", 5, 22, 37, True, future=True)


# ============================================================
# TEST 1-5: Normal city scenarios
# ============================================================

def test_01_tokyo_normal_day(tokyo_record):
    """Test 1: Tokyo normal day — record is valid and confirmed."""
    assert tokyo_record.city == "tokyo"
    assert tokyo_record.confirmation_status == "CONFIRMED"
    assert tokyo_record.iana_timezone == "Asia/Tokyo"
    assert tokyo_record.local_sunrise == "05:22:37"
    assert tokyo_record.utc_timestamp_ms > 0
    assert tokyo_record.candle_open_utc_ms <= tokyo_record.utc_timestamp_ms
    # candle open must be exactly on the minute
    assert tokyo_record.candle_open_utc_ms % 60000 == 0

def test_02_london_winter(london_winter_record):
    """Test 2: London winter day — uses GMT (UTC+0)."""
    assert london_winter_record.city == "london"
    assert london_winter_record.iana_timezone == "Europe/London"
    # In January, London is UTC+0, so UTC hour == local hour
    utc_dt = datetime.fromtimestamp(london_winter_record.utc_timestamp_ms / 1000, tz=pytz.utc)
    assert utc_dt.hour == 7
    assert utc_dt.minute == 58

def test_03_london_summer(london_summer_record):
    """Test 3: London summer day — uses BST (UTC+1)."""
    assert london_summer_record.city == "london"
    utc_dt = datetime.fromtimestamp(london_summer_record.utc_timestamp_ms / 1000, tz=pytz.utc)
    # In June, London is BST (UTC+1), so UTC = local - 1 hour
    assert utc_dt.hour == 3  # 04:49 BST = 03:49 UTC
    assert utc_dt.minute == 49

def test_04_nyc_winter(nyc_winter_record):
    """Test 4: New York winter day — uses EST (UTC-5)."""
    assert nyc_winter_record.city == "newyork"
    utc_dt = datetime.fromtimestamp(nyc_winter_record.utc_timestamp_ms / 1000, tz=pytz.utc)
    # 07:17 EST = 12:17 UTC
    assert utc_dt.hour == 12
    assert utc_dt.minute == 17

def test_05_nyc_summer(nyc_summer_record):
    """Test 5: New York summer day — uses EDT (UTC-4)."""
    assert nyc_summer_record.city == "newyork"
    utc_dt = datetime.fromtimestamp(nyc_summer_record.utc_timestamp_ms / 1000, tz=pytz.utc)
    # 05:28 EDT = 09:28 UTC
    assert utc_dt.hour == 9
    assert utc_dt.minute == 28


# ============================================================
# TEST 6: DST transitions
# ============================================================

def test_06_dst_london_transition():
    """Test 6: London DST — last GMT day vs first BST day (2026)."""
    # UK DST 2026: clocks spring forward on March 29 at 1:00 AM
    # March 28: GMT (UTC+0), sunrise ~06:17
    # March 29: BST (UTC+1), sunrise ~06:15 (local), but UTC = 05:15
    rec_gmt = make_record("london", "2026-03-28", 6, 17, 0, False)
    rec_bst = make_record("london", "2026-03-29", 6, 15, 0, False)

    utc_gmt = datetime.fromtimestamp(rec_gmt.utc_timestamp_ms / 1000, tz=pytz.utc)
    utc_bst = datetime.fromtimestamp(rec_bst.utc_timestamp_ms / 1000, tz=pytz.utc)

    # GMT: UTC = local (no offset)
    assert utc_gmt.hour == 6
    assert utc_gmt.minute == 17

    # BST: UTC = local - 1 hour
    assert utc_bst.hour == 5
    assert utc_bst.minute == 15


def test_06b_dst_newyork_transition():
    """Test 6b: NYC DST — last EST day vs first EDT day (2026)."""
    # US DST 2026: clocks spring forward March 8 at 2:00 AM
    # March 7: EST (UTC-5), sunrise ~06:56
    # March 8: EDT (UTC-4), sunrise ~07:54 (local) -> UTC = 11:54
    rec_est = make_record("newyork", "2026-03-07", 6, 56, 0, False)
    rec_edt = make_record("newyork", "2026-03-08", 7, 54, 0, False)

    utc_est = datetime.fromtimestamp(rec_est.utc_timestamp_ms / 1000, tz=pytz.utc)
    utc_edt = datetime.fromtimestamp(rec_edt.utc_timestamp_ms / 1000, tz=pytz.utc)

    # EST: UTC = local + 5
    assert utc_est.hour == 11  # 06:56 EST = 11:56 UTC
    assert utc_est.minute == 56

    # EDT: UTC = local + 4
    assert utc_edt.hour == 11  # 07:54 EDT = 11:54 UTC
    assert utc_edt.minute == 54


# ============================================================
# TEST 7-8: Precision and minute boundary
# ============================================================

def test_07_sunrise_with_seconds(tokyo_record):
    """Test 7: Sunrise with seconds precision — stored verbatim."""
    assert tokyo_record.has_seconds is True
    assert tokyo_record.local_sunrise_ss == 37
    assert ":37" in tokyo_record.local_sunrise


@pytest.mark.parametrize("hh,mm,ss,expected_candle_mm", [
    (5, 22, 0,  22),  # exactly on minute boundary
    (5, 22, 1,  22),  # 1 second in
    (5, 22, 30, 22),  # mid-minute
    (5, 22, 59, 22),  # last second of minute
    (5, 23, 0,  23),  # next minute exactly
])
def test_08_candle_selection_precision(hh, mm, ss, expected_candle_mm):
    """Test 8: Candle selection for various sunrise seconds. Verifies spec section 9."""
    rec = make_record("tokyo", "2026-09-14", hh, mm, ss, True)
    # Decode candle open time back to UTC datetime
    candle_dt = datetime.fromtimestamp(rec.candle_open_utc_ms / 1000, tz=pytz.utc)
    # Convert to local Tokyo time
    jst = pytz.timezone("Asia/Tokyo")
    candle_local = candle_dt.astimezone(jst)
    assert candle_local.hour == hh
    assert candle_local.minute == expected_candle_mm
    assert candle_local.second == 0
    # candle_open_utc_ms must be exactly on a minute boundary
    assert rec.candle_open_utc_ms % 60000 == 0
    # sunrise must fall within the candle's 60-second window
    assert rec.candle_open_utc_ms <= rec.utc_timestamp_ms < rec.candle_open_utc_ms + 60000


# ============================================================
# TEST 10: Future sunrise rejection  (CRITICAL)
# ============================================================

def test_10_future_sunrise_rejection(future_record):
    """Test 10: Future sunrises must NEVER be confirmed."""
    assert not is_confirmed(future_record)
    assert future_record.confirmation_status == "PENDING"
    # is_confirmed must return False
    assert future_record.utc_timestamp_ms > int(time.time() * 1000)


def test_10b_past_sunrise_is_confirmed(tokyo_record):
    """Complementary: past sunrises must be confirmed."""
    # tokyo_record is from 2026-09-14 (past relative to test run in same timeframe)
    # We test is_confirmed logic directly
    # Manually set a clearly-past timestamp
    tokyo_record.utc_timestamp_ms = int(time.time() * 1000) - 3600 * 1000  # 1 hour ago
    assert is_confirmed(tokyo_record)


# ============================================================
# TEST 11: Source failure handling
# ============================================================

def test_11_source_failure_returns_none():
    """Test 11: When timeanddate.com is unreachable, return None, never invent data."""
    from unittest.mock import patch
    import sunrise_fetcher as sf
    # Temporarily clear the in-memory cache to force a fetch attempt
    original_cache = sf.load_cache()
    test_date = date(2020, 1, 15)  # historical date, far from any cached entry
    cache_key = "tokyo_2020-01-15"
    cache = dict(original_cache)
    cache.pop(cache_key, None)

    with patch("sunrise_fetcher.load_cache", return_value=cache), \
         patch("sunrise_fetcher._get_playwright_html", return_value=None):
        result = sf.fetch_sunrise("tokyo", test_date)
        assert result is None


# ============================================================
# TEST 12: Timezone invariance  (chart timezone change)
# ============================================================

def test_12_utc_timestamp_timezone_invariance(tokyo_record):
    """
    Test 12: The absolute UTC timestamp must be the same regardless
    of which timezone we display it in.
    """
    utc_ms = tokyo_record.utc_timestamp_ms

    # Display in UTC
    utc_dt = datetime.fromtimestamp(utc_ms / 1000, tz=pytz.utc)
    # Display in Tokyo
    jst_dt = datetime.fromtimestamp(utc_ms / 1000, tz=pytz.timezone("Asia/Tokyo"))
    # Display in New York
    ny_dt  = datetime.fromtimestamp(utc_ms / 1000, tz=pytz.timezone("America/New_York"))
    # Display in London
    lon_dt = datetime.fromtimestamp(utc_ms / 1000, tz=pytz.timezone("Europe/London"))

    # All represent the SAME absolute moment
    assert utc_dt.timestamp() == jst_dt.timestamp()
    assert utc_dt.timestamp() == ny_dt.timestamp()
    assert utc_dt.timestamp() == lon_dt.timestamp()

    # Local time differs by timezone offset
    # Tokyo is UTC+9, so local hour = 5, UTC hour = 5-9 = -4 (20 prev day)
    assert jst_dt.hour == 5
    assert jst_dt.minute == 22


# ============================================================
# TEST 15: Rolling 12-day window deletion
# ============================================================

def test_15_rolling_12_day_window():
    """Test 15: Only 12 most recent dates kept in CSV."""
    from seed_generator import generate_csv
    import tempfile, csv

    records = []
    # Create 13 records for Tokyo, one per day going back from today
    today = datetime.utcnow().date()
    for i in range(13):
        d = today - timedelta(days=i + 1)  # all in the past
        rec = make_record("tokyo", d.strftime("%Y-%m-%d"), 5, 22, 0, False)
        rec.confirmation_status = "CONFIRMED"
        records.append(rec)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_csv(records, "tokyo", output_dir=tmpdir, max_days=12)
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 12, f"Expected 12 rows, got {len(rows)}"


# ============================================================
# TEST 16: New confirmed day insertion
# ============================================================

def test_16_new_confirmed_day_insertion():
    """Test 16: A newly confirmed sunrise is added to the CSV."""
    from seed_generator import generate_csv
    import tempfile, csv

    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)
    rec = make_record("tokyo", yesterday.strftime("%Y-%m-%d"), 5, 22, 0, False)
    rec.confirmation_status = "CONFIRMED"

    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_csv([rec], "tokyo", output_dir=tmpdir)
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert int(float(rows[0]["open"])) == 522  # 05:22


# ============================================================
# TEST 17: Partial-day behavior
# ============================================================

def test_17_partial_day_behavior():
    """
    Test 17: Only sunrises that have occurred appear.
    Cities can be on different eligibility states at the same moment.
    """
    # Tokyo has already happened (far in past)
    tokyo = make_record("tokyo", "2026-09-14", 5, 22, 0, False)
    tokyo.utc_timestamp_ms = int(time.time() * 1000) - 3600 * 1000  # 1h ago

    # London hasn't happened yet (future)
    london = make_record("london", "2026-09-14", 6, 30, 0, False)
    london.utc_timestamp_ms = int(time.time() * 1000) + 3600 * 1000  # 1h future

    assert is_confirmed(tokyo)
    assert not is_confirmed(london)


# ============================================================
# TEST parsing
# ============================================================

@pytest.mark.parametrize("raw,expected", [
    ("5:22 am",       (5, 22, 0, False)),
    ("05:22",         (5, 22, 0, False)),
    ("5:22:37 am",    (5, 22, 37, True)),
    ("05:22:37",      (5, 22, 37, True)),
    ("12:00 am",      (0,  0, 0, False)),   # midnight
    ("12:00 pm",      (12, 0, 0, False)),   # noon
    ("5:22 (82 deg)", (5, 22, 0, False)),   # with azimuth stripped
])
def test_parse_time_str_variants(raw, expected):
    """Verify time string parser handles all timeanddate.com formats."""
    result = _parse_time_str(raw)
    assert result == expected, f"For input {raw!r}: expected {expected}, got {result}"


def test_parse_time_str_invalid():
    """Invalid time strings must return None, never guess."""
    assert _parse_time_str("not a time") is None
    assert _parse_time_str("") is None
    assert _parse_time_str("25:00") is None  # invalid hour


# ============================================================
# TEST 25: Data source format change detection
# ============================================================

def test_25_html_structure_change_detection():
    """Test 25: If HTML structure changes, parser returns None and logs CRITICAL."""
    # Simulate broken HTML with no as-monthsun table
    broken_html = "<html><body><p>No table here</p></body></html>"
    result = _parse_monthly_table(broken_html, 14)
    assert result is None