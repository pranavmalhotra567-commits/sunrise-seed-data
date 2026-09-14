# Data Schema

Complete reference for all data structures in the Confirmed Sunrise Zones system.

---

## 1. SunriseRecord (Python Dataclass)

```python
@dataclass
class SunriseRecord:
    city: str                  # "tokyo" | "london" | "newyork"
    local_date: str            # "YYYY-MM-DD" (local date in city timezone)
    local_sunrise: str         # "HH:MM:SS" or "HH:MM" (from timeanddate.com)
    local_sunrise_hh: int      # hour component (0-23)
    local_sunrise_mm: int      # minute component (0-59)
    local_sunrise_ss: int      # second component (0 if not available from source)
    has_seconds: bool          # True if seconds were available from source
    iana_timezone: str         # "Asia/Tokyo" | "Europe/London" | "America/New_York"
    utc_timestamp_ms: int      # UTC milliseconds of the sunrise event itself
    candle_open_utc_ms: int    # UTC ms of 1-min candle open (floor to minute)
    source: str                # always "timeanddate.com"
    source_url: str            # exact URL scraped
    confirmation_status: str   # "CONFIRMED" | "PENDING" | "UNAVAILABLE"
    fetched_at: str            # ISO 8601 UTC timestamp of when the record was fetched
```

### Example (Tokyo, 2026-09-14, sunrise 05:22:37 JST)

```json
{
  "city": "tokyo",
  "local_date": "2026-09-14",
  "local_sunrise": "05:22:37",
  "local_sunrise_hh": 5,
  "local_sunrise_mm": 22,
  "local_sunrise_ss": 37,
  "has_seconds": true,
  "iana_timezone": "Asia/Tokyo",
  "utc_timestamp_ms": 1757801557000,
  "candle_open_utc_ms": 1757801520000,
  "source": "timeanddate.com",
  "source_url": "https://www.timeanddate.com/sun/japan/tokyo",
  "confirmation_status": "CONFIRMED",
  "fetched_at": "2026-09-14T06:00:00Z"
}
```

### UTC Timestamp Derivation

```
Local:  2026-09-14 05:22:37 JST  (Asia/Tokyo = UTC+9, no DST)
UTC:    2026-09-13 20:22:37 UTC

utc_timestamp_ms    = 1757801557000  (exact sunrise moment)
candle_open_utc_ms  = 1757801520000  (20:22:00 UTC — the minute boundary)

The sunrise (20:22:37) falls within candle [20:22:00, 20:23:00).
Specification requirement (section 9): candle_open <= sunrise < candle_close  ✓
```

---

## 2. CrossCheckResult (Python Dataclass)

```python
@dataclass
class CrossCheckResult:
    city: str
    local_date: str
    source_local_sunrise: str       # from timeanddate.com (AUTHORITATIVE — never replaced)
    calculated_local_sunrise: str   # from astral library (validation only)
    delta_seconds: int              # abs(source - calculated) in seconds
    validation_status: str          # "PASS" | "WARNING" | "FAIL"
    tolerance_seconds: int          # 120
    note: str
```

### Status Thresholds

| Delta | Status | Action |
|---|---|---|
| <= 30s | PASS | Record written with code 1 (VERIFIED) |
| 31–120s | WARNING | Record written with code 2 (WARNING) |
| > 120s | FAIL | Record written with code 2 (WARNING) — timeanddate value preserved |

---

## 3. CSV File Format

### File Locations

```
data/SUNRISE_TOKYO.csv
data/SUNRISE_LONDON.csv
data/SUNRISE_NYC.csv
```

### Header Row (required by Pine Seeds)

```
time,open,high,low,close,volume
```

### OHLCV Slot Encoding Table

| CSV Column | Encoded Value | Decode Formula | Example |
|---|---|---|---|
| `time` | `candle_open_utc_ms` (UTC ms) | timestamp in ms | `1757801520000` |
| `open` | `hh * 100 + mm` | `hhmm // 100` = hh, `hhmm % 100` = mm | `522` → 05:22 |
| `high` | `ss` (seconds) | direct | `37` |
| `low` | `yyyymmdd` integer | split digits | `20260914` → 2026-09-14 |
| `close` | status code | 1=VERIFIED, 2=WARNING, 0=UNAVAILABLE | `1` |
| `volume` | `0` (reserved) | — | `0` |

### Example Rows

**Tokyo — 2026-09-14 — 05:22:37 JST — VERIFIED:**
```
1757801520000,522,37,20260914,1,0
```

**London — 2026-06-15 — 04:49 BST (minute-only precision) — VERIFIED:**
```
1781504940000,449,0,20260615,1,0
```

**New York — 2026-01-15 — 07:17 EST (minute-only precision) — WARNING:**
```
1768463820000,717,0,20260115,2,0
```

### Decode a Row (Python)

```python
def decode_row(row: dict) -> dict:
    hhmm     = int(float(row["open"]))
    date_int = int(float(row["low"]))
    yyyy = date_int // 10000
    mo   = (date_int % 10000) // 100
    dy   = date_int % 100
    return {
        "candle_open_utc_ms": int(float(row["time"])),
        "local_sunrise_hh":   hhmm // 100,
        "local_sunrise_mm":   hhmm % 100,
        "local_sunrise_ss":   int(float(row["high"])),
        "local_date":         f"{yyyy:04d}-{mo:02d}-{dy:02d}",
        "status_code":        int(float(row["close"])),
        "status_str": {1: "VERIFIED", 2: "WARNING", 0: "UNAVAILABLE"}.get(int(float(row["close"])), "UNKNOWN"),
    }
```

### Pine Script Decode (OHLCV → Metadata)

```pinescript
// When request.seed() returns non-na on a bar:
int   sunrise_hhmm  = int(tk_hhmm)        // open column
int   sunrise_sec   = int(tk_sec)          // high column
int   date_int      = int(tk_date)         // low column
int   status_code   = int(tk_status)       // close column
// bar's actual high/low are used for zone geometry (NOT from seed data)
float zone_high     = high
float zone_low      = low
```

---

## 4. Validation Rules

Enforced in `sunrise_fetcher.py` before any record is accepted:

| # | Rule | Check | Failure Action |
|---|---|---|---|
| V1 | City must be known | `city_key in CITY_CONFIGS` | Return None + error log |
| V2 | HTTP must succeed | status 200, 3 retries | Return None + CRITICAL log |
| V3 | HTML table must exist | `table#as-monthsun` found | Return None + CRITICAL log (structure change) |
| V4 | Time must parse | `_parse_time_str()` not None | Return None + error log |
| V5 | Hour in range 03–09 | `3 <= hh <= 9` | Return None + error log |
| V6 | UTC conversion must succeed | pytz must not raise | Return None + error log |
| V7 | Sunrise must have occurred | `utc_ms < time.time() * 1000` | Return None (future-date protection) |
| V8 | Cross-check delta <= 120s | `delta_seconds <= 120` | Write with WARNING status (code 2) |

### Candle Open Timestamp Derivation

```
candle_open_utc_ms = floor(utc_sunrise_ms / 60000) * 60000

Equivalently in Python:
    utc_dt_floor = utc_dt.replace(second=0, microsecond=0)
    candle_open_ms = int(utc_dt_floor.timestamp() * 1000)

The resulting candle satisfies:
    candle_open_utc_ms <= utc_sunrise_ms < candle_open_utc_ms + 60000
```

---

## 5. Status Codes

| Code | Name | Pine diagnostic color | Meaning |
|---|---|---|---|
| `1` | VERIFIED | Green | timeanddate confirmed; cross-check PASS |
| `2` | WARNING | Orange | Cross-check WARNING/FAIL; use with caution |
| `0` | UNAVAILABLE | Red | Source data could not be verified |

---

## 6. City Definitions (as used by timeanddate.com)

| City | URL Slug | Latitude | Longitude | Elevation | Timezone |
|---|---|---|---|---|---|
| Tokyo | `japan/tokyo` | 35.6895°N | 139.6917°E | 40m | Asia/Tokyo (UTC+9, no DST) |
| London | `uk/london` | 51.5085°N | 0.1257°W | 25m | Europe/London (GMT/BST) |
| New York | `usa/new-york` | 40.7143°N | 74.0060°W | 10m | America/New_York (EST/EDT) |

Source pages:
- https://www.timeanddate.com/sun/japan/tokyo
- https://www.timeanddate.com/sun/uk/london
- https://www.timeanddate.com/sun/usa/new-york

---

## 7. Cache Schema

Location: `cache/sunrise_cache.json`

```json
{
  "tokyo_2026-09-14": { /* SunriseRecord as dict */ },
  "london_2026-09-14": { /* SunriseRecord as dict */ },
  "newyork_2026-09-14": { /* SunriseRecord as dict */ }
}
```

Keys: `"{city}_{YYYY-MM-DD}"`

---

## 8. Validated Records Schema

Location: `validated/sunrise_records.json`

```json
[
  {
    "city": "tokyo",
    "local_date": "2026-09-14",
    "local_sunrise": "05:22:37",
    "has_seconds": true,
    "iana_timezone": "Asia/Tokyo",
    "utc_timestamp_ms": 1757801557000,
    "candle_open_utc_ms": 1757801520000,
    "source": "timeanddate.com",
    "source_url": "https://www.timeanddate.com/sun/japan/tokyo",
    "confirmation_status": "CONFIRMED",
    "crosscheck": {
      "status": "PASS",
      "delta_seconds": 4,
      "calculated": "05:22:41",
      "note": "Delta 4s within acceptable range"
    }
  }
]
```
