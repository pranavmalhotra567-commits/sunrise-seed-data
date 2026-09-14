#!/usr/bin/env python3
"""
run_daily_update.py
Orchestrator: fetch confirmed sunrises -> cross-check -> generate CSVs.

Exit codes:
  0 = success
  1 = critical failure (timeanddate unreachable, no data written)
  2 = partial failure (some cities failed, existing CSVs preserved)
"""
import sys
import os
import logging
import json
from datetime import datetime

from sunrise_fetcher import fetch_rolling_window, CITY_CONFIGS
from astral_crosscheck import crosscheck
from seed_generator import generate_all_csvs

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger("run_daily_update")

FORCE_REFETCH = os.environ.get("FORCE_REFETCH", "false").lower() == "true"
MAX_DAYS = 12


def main():
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data", exist_ok=True)
    os.makedirs("validated", exist_ok=True)

    logger.info("=" * 60)
    logger.info("Confirmed Sunrise Zones - Daily Update")
    logger.info("Run time: %s UTC", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    if FORCE_REFETCH:
        logger.info("FORCE_REFETCH enabled: clearing cache")
        import shutil
        if os.path.exists("cache"):
            shutil.rmtree("cache")

    # Step 1: Fetch confirmed sunrise records
    logger.info("Fetching rolling window (%d days x 3 cities)...", MAX_DAYS)
    records = fetch_rolling_window(days=MAX_DAYS)

    if not records:
        logger.critical("No sunrise records fetched. timeanddate.com may be unreachable.")
        logger.critical("Existing CSV files are preserved. No new zones will be created.")
        logger.critical("Sunrise data unavailable -- no new zones will be created until source data is verified.")
        return 1

    logger.info("Fetched %d confirmed sunrise records", len(records))

    # Step 2: Astronomical cross-check
    logger.info("Running astral cross-check on all records...")
    crosscheck_results = {}
    failed_crosschecks = []

    for rec in records:
        try:
            xr = crosscheck(rec)
            cache_key = f"{rec.city}_{rec.local_date}"
            crosscheck_results[cache_key] = xr
            if xr.validation_status == "FAIL":
                failed_crosschecks.append((rec, xr))
                logger.warning(
                    "Cross-check FAIL: %s %s | source=%s | calc=%s | delta=%ds",
                    rec.city, rec.local_date,
                    xr.source_local_sunrise, xr.calculated_local_sunrise,
                    xr.delta_seconds
                )
            elif xr.validation_status == "WARNING":
                logger.warning(
                    "Cross-check WARNING: %s %s | delta=%ds",
                    rec.city, rec.local_date, xr.delta_seconds
                )
            else:
                logger.info(
                    "Cross-check PASS: %s %s | delta=%ds",
                    rec.city, rec.local_date, xr.delta_seconds
                )
        except Exception as exc:
            logger.error("Cross-check error for %s %s: %s", rec.city, rec.local_date, exc)

    # Step 3: Save validated records JSON (for audit trail)
    validated = [
        {
            "city": r.city,
            "local_date": r.local_date,
            "local_sunrise": r.local_sunrise,
            "has_seconds": r.has_seconds,
            "iana_timezone": r.iana_timezone,
            "utc_timestamp_ms": r.utc_timestamp_ms,
            "candle_open_utc_ms": r.candle_open_utc_ms,
            "source": r.source,
            "source_url": r.source_url,
            "confirmation_status": r.confirmation_status,
            "crosscheck": crosscheck_results.get(f"{r.city}_{r.local_date}", None) and {
                "status": crosscheck_results[f"{r.city}_{r.local_date}"].validation_status,
                "delta_seconds": crosscheck_results[f"{r.city}_{r.local_date}"].delta_seconds,
                "calculated": crosscheck_results[f"{r.city}_{r.local_date}"].calculated_local_sunrise,
                "note": crosscheck_results[f"{r.city}_{r.local_date}"].note,
            },
        }
        for r in records
    ]
    validated_path = os.path.join("validated", "sunrise_records.json")
    with open(validated_path, "w", encoding="utf-8") as f:
        json.dump(validated, f, indent=2)
    logger.info("Validated records saved to %s", validated_path)

    # Step 4: Generate CSVs
    logger.info("Generating seed CSV files...")
    try:
        paths = generate_all_csvs(records, output_dir="data",
                                   crosscheck_results=crosscheck_results,
                                   max_days=MAX_DAYS)
        for city, path in paths.items():
            logger.info("Written: %s -> %s", city, path)
    except Exception as exc:
        logger.critical("CSV generation failed: %s", exc)
        return 1

    # Summary
    logger.info("=" * 60)
    logger.info("Update complete.")
    logger.info("  Records fetched:  %d", len(records))
    logger.info("  Cross-check FAIL: %d", len(failed_crosschecks))
    logger.info("  CSV files written: %d", len(paths))
    logger.info("=" * 60)

    if failed_crosschecks:
        logger.warning("%d records had cross-check failures (still written with WARNING status)", len(failed_crosschecks))
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())