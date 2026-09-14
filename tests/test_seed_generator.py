import pytest
import tempfile
import csv
import time
from datetime import datetime, timedelta
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sunrise_fetcher import SunriseRecord, _compute_timestamps
from seed_generator import generate_csv, generate_all_csvs, _decode_row, CITY_FILE_MAP


def make_past_record(city, date_str, hh=5, mm=22, ss=37, has_sec=True):
    tz_map = {"tokyo": "Asia/Tokyo", "london": "Europe/London", "newyork": "America/New_York"}
    iana = tz_map[city]
    yr, mo, dy = int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10])
    utc_ms, candle_ms = _compute_timestamps(iana, yr, mo, dy, hh, mm, ss)
    local_sunrise = f"{hh:02d}:{mm:02d}:{ss:02d}" if has_sec else f"{hh:02d}:{mm:02d}"
    return SunriseRecord(
        city=city, local_date=date_str, local_sunrise=local_sunrise,
        local_sunrise_hh=hh, local_sunrise_mm=mm, local_sunrise_ss=ss,
        has_seconds=has_sec, iana_timezone=iana,
        utc_timestamp_ms=utc_ms, candle_open_utc_ms=candle_ms,
        source="timeanddate.com",
        source_url=f"https://www.timeanddate.com/sun/japan/tokyo",
        confirmation_status="CONFIRMED",
        fetched_at="2026-09-14T06:00:00Z",
    )


def test_csv_header():
    """CSV must start with the correct header."""
    rec = make_past_record("tokyo", "2026-09-01")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_csv([rec], "tokyo", output_dir=tmpdir)
        with open(path, newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == ["time", "open", "high", "low", "close", "volume"]


def test_ohlcv_encoding_correctness():
    """Each OHLCV slot must encode the correct value."""
    rec = make_past_record("tokyo", "2026-09-14", hh=5, mm=22, ss=37, has_sec=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_csv([rec], "tokyo", output_dir=tmpdir)
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        row = rows[0]
        # time = candle_open_utc_ms
        assert int(row["time"]) == rec.candle_open_utc_ms
        assert int(row["time"]) % 60000 == 0  # must be on exact minute
        # open = HHMM = 5*100+22 = 522
        assert int(float(row["open"])) == 522
        # high = seconds = 37
        assert int(float(row["high"])) == 37
        # low = YYYYMMDD = 20260914
        assert int(float(row["low"])) == 20260914
        # close = status code
        assert int(float(row["close"])) in (0, 1, 2)
        # volume = 0
        assert int(float(row["volume"])) == 0


def test_round_trip_encoding_decoding():
    """Encoded values must decode back to original sunrise metadata."""
    hh, mm, ss = 5, 22, 37
    date_str = "2026-09-14"
    rec = make_past_record("tokyo", date_str, hh=hh, mm=mm, ss=ss)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_csv([rec], "tokyo", output_dir=tmpdir)
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        decoded = _decode_row(rows[0])

    assert decoded["local_sunrise_hh"] == hh
    assert decoded["local_sunrise_mm"] == mm
    assert decoded["local_sunrise_ss"] == ss
    assert decoded["local_date"] == date_str
    assert decoded["candle_open_utc_ms"] == rec.candle_open_utc_ms


def test_rolling_window_12_day():
    """Only the 12 most recent records are written."""
    today = datetime.utcnow().date()
    records = []
    for i in range(15):
        d = today - timedelta(days=i + 1)
        records.append(make_past_record("tokyo", d.strftime("%Y-%m-%d")))

    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_csv(records, "tokyo", output_dir=tmpdir, max_days=12)
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    assert len(rows) == 12


def test_future_records_excluded():
    """Records whose sunrise hasn't occurred must never appear in CSV."""
    past_rec = make_past_record("tokyo", "2026-09-01")
    # Build a "future" record by pushing utc_timestamp_ms forward
    future_rec = make_past_record("tokyo", "2026-09-02")
    future_rec.utc_timestamp_ms = int(time.time() * 1000) + 86400 * 1000  # tomorrow
    future_rec.candle_open_utc_ms = future_rec.utc_timestamp_ms

    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_csv([past_rec, future_rec], "tokyo", output_dir=tmpdir)
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    assert len(rows) == 1  # only the past record


def test_only_confirmed_records_written():
    """Records with status != CONFIRMED must not appear in CSV."""
    confirmed = make_past_record("tokyo", "2026-09-01")
    pending = make_past_record("tokyo", "2026-09-02")
    pending.confirmation_status = "PENDING"

    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_csv([confirmed, pending], "tokyo", output_dir=tmpdir)
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    assert len(rows) == 1


def test_chronological_sort():
    """CSV rows must be sorted chronologically ascending (required by Pine Seeds)."""
    records = [
        make_past_record("tokyo", "2026-09-05"),
        make_past_record("tokyo", "2026-09-03"),
        make_past_record("tokyo", "2026-09-04"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_csv(records, "tokyo", output_dir=tmpdir)
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    timestamps = [int(r["time"]) for r in rows]
    assert timestamps == sorted(timestamps)


def test_generate_all_csvs_creates_three_files():
    """generate_all_csvs must produce one CSV per city."""
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)
    records = [
        make_past_record("tokyo",   yesterday.strftime("%Y-%m-%d"), hh=5, mm=22),
        make_past_record("london",  yesterday.strftime("%Y-%m-%d"), hh=6, mm=30),
        make_past_record("newyork", yesterday.strftime("%Y-%m-%d"), hh=7, mm=15),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = generate_all_csvs(records, output_dir=tmpdir)
        assert set(paths.keys()) == {"tokyo", "london", "newyork"}
        for city, path in paths.items():
            assert os.path.exists(path), f"CSV missing for {city}"
            assert os.path.basename(path) == CITY_FILE_MAP[city]


def test_city_isolation():
    """Each city's CSV must only contain records for that city."""
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)
    records = [
        make_past_record("tokyo",   yesterday.strftime("%Y-%m-%d"), hh=5, mm=22),
        make_past_record("london",  yesterday.strftime("%Y-%m-%d"), hh=6, mm=30),
        make_past_record("newyork", yesterday.strftime("%Y-%m-%d"), hh=7, mm=15),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = generate_all_csvs(records, output_dir=tmpdir)
        for city, path in paths.items():
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
            # Each file has exactly 1 record
            assert len(rows) == 1
            # Decode and verify the HHMM is correct for each city
            decoded = _decode_row(rows[0])
            if city == "tokyo":
                assert decoded["local_sunrise_hh"] == 5 and decoded["local_sunrise_mm"] == 22
            elif city == "london":
                assert decoded["local_sunrise_hh"] == 6 and decoded["local_sunrise_mm"] == 30
            elif city == "newyork":
                assert decoded["local_sunrise_hh"] == 7 and decoded["local_sunrise_mm"] == 15