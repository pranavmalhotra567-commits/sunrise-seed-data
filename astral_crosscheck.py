from dataclasses import dataclass
from datetime import datetime
import pytz
from astral import Observer
from astral.sun import sun

# ============================================================
# ASTRONOMICAL CROSS-CHECK  (validation only)
# Uses astral library with exact timeanddate.com coordinates.
# NEVER replaces the timeanddate value.
# The timeanddate value is always authoritative.
# ============================================================

# Exact coordinates matching timeanddate.com city definitions
CITY_LOCATIONS = {
    "tokyo":   Observer(latitude=35.6895, longitude=139.6917, elevation=40),
    "london":  Observer(latitude=51.5085, longitude=-0.1257,  elevation=25),
    "newyork": Observer(latitude=40.7143, longitude=-74.0060, elevation=10),
}


@dataclass
class CrossCheckResult:
    city: str
    local_date: str
    source_local_sunrise: str       # from timeanddate (authoritative)
    calculated_local_sunrise: str   # from astral (validation only)
    delta_seconds: int
    validation_status: str          # PASS | WARNING | FAIL
    tolerance_seconds: int
    note: str


def crosscheck(record) -> CrossCheckResult:
    """
    Validate a timeanddate SunriseRecord against an independent astronomical
    calculation using the astral library.

    Tolerance rules:
      delta <= 30s  : PASS
      delta <= 120s : WARNING (elevated but acceptable)
      delta >  120s : FAIL    (reject the record; something is wrong)

    IMPORTANT: This function never modifies the record.
    The timeanddate value remains authoritative regardless of this result.
    """
    observer = CITY_LOCATIONS.get(record.city)
    if observer is None:
        return CrossCheckResult(
            city=record.city, local_date=record.local_date,
            source_local_sunrise=record.local_sunrise,
            calculated_local_sunrise="N/A",
            delta_seconds=-1, validation_status="FAIL",
            tolerance_seconds=120,
            note=f"Unknown city key: {record.city}"
        )

    tz = pytz.timezone(record.iana_timezone)
    local_date_obj = datetime.strptime(record.local_date, "%Y-%m-%d").date()

    # Calculate sunrise via astral
    try:
        sun_times = sun(observer, date=local_date_obj, tzinfo=tz)
        calc_sunrise = sun_times["sunrise"]
    except Exception as exc:
        return CrossCheckResult(
            city=record.city, local_date=record.local_date,
            source_local_sunrise=record.local_sunrise,
            calculated_local_sunrise="ERROR",
            delta_seconds=-1, validation_status="FAIL",
            tolerance_seconds=120,
            note=f"Astral calculation error: {exc}"
        )

    # Convert source record to datetime for comparison
    from_utc = datetime.fromtimestamp(record.utc_timestamp_ms / 1000.0, tz=pytz.utc)
    source_dt = from_utc.astimezone(tz)

    delta = int(abs((calc_sunrise - source_dt).total_seconds()))

    if delta <= 30:
        status = "PASS"
        note = f"Delta {delta}s within acceptable range"
    elif delta <= 120:
        status = "WARNING"
        note = f"Delta {delta}s elevated but within tolerance (120s max)"
    else:
        status = "FAIL"
        note = f"Delta {delta}s exceeds tolerance of 120s -- source data suspect"

    return CrossCheckResult(
        city=record.city,
        local_date=record.local_date,
        source_local_sunrise=record.local_sunrise,
        calculated_local_sunrise=calc_sunrise.strftime("%H:%M:%S"),
        delta_seconds=delta,
        validation_status=status,
        tolerance_seconds=120,
        note=note,
    )