import os
import csv
import time
import datetime
from typing import List, Dict

from sunrise_fetcher import SunriseRecord, is_confirmed

# ============================================================
# SEED GENERATOR
# Generates CSV files in request.seed() format for TradingView.
# One CSV file per city, encoding sunrise data into OHLCV slots.
#
# ENCODING SCHEME (OHLCV slot multiplexing):
#   time   = candle_open_utc_ms  (UTC ms of 1-min candle open)
#   open   = HHMM integer        (e.g. 05:22 -> 522)
#   high   = SS integer          (seconds, e.g. 37)
#   low    = YYYYMMDD integer    (local date, e.g. 20260914)
#   close  = status code         (1=VERIFIED, 2=WARNING, 0=UNAVAILABLE)
#   volume = 0                   (reserved)
#
# Example row for Tokyo sunrise at 05:22:37 on 2026-09-14:
#   1757801520000,522,37,20260914,1,0
#
# The Pine Script indicator decodes these values to reconstruct
# the sunrise metadata and draw the zone box.
# ============================================================

CITY_FILE_MAP = {
    "tokyo":   "Z_TOKYO.csv",
    "london":  "Z_LONDON.csv",
    "newyork": "Z_NYC.csv",
}

CSV_HEADER = ["time", "open", "high", "low", "close", "volume"]


def _encode_record(record: SunriseRecord, status_code: int = 1) -> list:
    """
    Encode a SunriseRecord into a CSV row using OHLCV slot multiplexing.
    Returns a list: [time, open, high, low, close, volume]
    """
    hhmm = record.local_sunrise_hh * 100 + record.local_sunrise_mm
    ss   = record.local_sunrise_ss
    date_int = int(record.local_date.replace("-", ""))
    # Use raw Unix milliseconds to guarantee exact match with TradingView's internal time
    return [record.candle_open_utc_ms, hhmm, date_int, 0, status_code, ss + 1]


def _decode_row(row: dict) -> dict:
    """
    Reverse the encoding: decode a CSV row back to sunrise metadata.
    Useful for verification and testing.
    """
    hhmm     = int(float(row["open"]))
    hh       = hhmm // 100
    mm       = hhmm % 100
    ss       = int(float(row["high"]))
    date_int = int(float(row["low"]))
    status   = int(float(row["close"]))
    yyyy = date_int // 10000
    mo   = (date_int % 10000) // 100
    dy   = date_int % 100
    return {
        "candle_open_utc_ms": int(float(row["time"])),
        "local_sunrise_hh": hh,
        "local_sunrise_mm": mm,
        "local_sunrise_ss": ss,
        "local_date": f"{yyyy:04d}-{mo:02d}-{dy:02d}",
        "status_code": status,
        "status_str": {1: "VERIFIED", 2: "WARNING", 0: "UNAVAILABLE"}.get(status, "UNKNOWN"),
    }


def generate_csv(
    records: List[SunriseRecord],
    city_key: str,
    output_dir: str = "data",
    crosscheck_results: dict = None,
    max_days: int = 12,
) -> str:
    """
    Generate a CSV file for one city.

    Args:
        records:            All SunriseRecord objects (mixed cities OK)
        city_key:           "tokyo" | "london" | "newyork"
        output_dir:         Directory to write CSV files into
        crosscheck_results: Optional dict of {cache_key: CrossCheckResult}
        max_days:           Rolling window size (default 12)

    Returns:
        Absolute path of the written CSV file.

    Raises:
        ValueError: if city_key is unknown
    """
    if city_key not in CITY_FILE_MAP:
        raise ValueError(f"Unknown city key: {city_key!r}")

    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, CITY_FILE_MAP[city_key])

    now_ms = int(time.time() * 1000)

    # Filter: correct city, CONFIRMED status, past (not future)
    city_records = [
        r for r in records
        if r.city == city_key
        and r.confirmation_status == "CONFIRMED"
        and r.utc_timestamp_ms < now_ms
    ]

    # Sort chronologically ascending (required by Pine Seeds)
    city_records.sort(key=lambda r: r.candle_open_utc_ms)

    # Apply rolling window: keep last max_days records
    city_records = city_records[-max_days:]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for rec in city_records:
            # Determine status code from cross-check results
            status_code = 1  # default: VERIFIED
            if crosscheck_results:
                cache_key = f"{rec.city}_{rec.local_date}"
                xr = crosscheck_results.get(cache_key)
                if xr:
                    if xr.validation_status == "PASS":
                        status_code = 1  # VERIFIED
                    elif xr.validation_status == "WARNING":
                        status_code = 2  # WARNING
                    elif xr.validation_status == "FAIL":
                        status_code = 2  # WARNING (not discarded, just flagged)
            row = _encode_record(rec, status_code)
            writer.writerow(row)

    return os.path.abspath(filepath)


def generate_all_csvs(
    records: List[SunriseRecord],
    output_dir: str = "data",
    crosscheck_results: dict = None,
    max_days: int = 12,
) -> Dict[str, str]:
    """
    Generate CSV files for all 3 cities.
    Returns dict of {city_key: filepath}.
    """
    return {
        city: generate_csv(records, city, output_dir, crosscheck_results, max_days)
        for city in CITY_FILE_MAP
    }
