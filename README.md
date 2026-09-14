# Confirmed Sunrise Zones

A production-quality TradingView indicator that marks the exact 1-minute candle of confirmed astronomical sunrise for **Tokyo**, **London**, and **New York City**, using **timeanddate.com** as the authoritative data source.

---

## 1. Overview

This system bridges an external data source (timeanddate.com) into TradingView by using a three-tier architecture:

1. **Python data service** — fetches, validates, and encodes sunrise data
2. **GitHub repository** — hosts the encoded CSV files that TradingView can read
3. **Pine Script v6 indicator** — reads the data, matches it to the exact 1-minute candle, and draws sunrise zone boxes

**What makes this different from a simple sunrise calculator:**
- Uses timeanddate.com as the authoritative source (not predicted astronomical values)
- Only displays confirmed past sunrises (never future predictions)
- Independent astronomical cross-check via the `astral` library validates every record
- Explicit rolling 12-day window with manual box deletion

---

## 2. Architecture

```
timeanddate.com
  |
  | HTTP scrape (Python service, 4x daily via GitHub Actions)
  |
sunrise_fetcher.py
  |-- parse HTML (monthly table: minute precision)
  |-- parse daily page (today: second precision)
  |-- validate (future-date guard, hour range, timezone)
  |
astral_crosscheck.py
  |-- independent calculation using astral library
  |-- compare delta (must be within 120 seconds)
  |-- FAIL if delta > 120s (record flagged)
  |
seed_generator.py
  |-- encode into OHLCV CSV format (OHLCV slot multiplexing)
  |-- rolling 12-day window
  |-- write data/SUNRISE_TOKYO.csv
  |-- write data/SUNRISE_LONDON.csv
  |-- write data/SUNRISE_NYC.csv
  |
GitHub Repository (public)
  |-- data/SUNRISE_TOKYO.csv
  |-- data/SUNRISE_LONDON.csv
  |-- data/SUNRISE_NYC.csv
  |
TradingView request.seed()  [cache TTL ~10-15 min]
  |
confirmed_sunrise_zones.pine
  |-- reads seed data on exact 1-min candle
  |-- draws wick-to-wick box (HIGH to LOW)
  |-- extend.right to current chart edge
  |-- rolling 12-day window enforcement
  |-- diagnostic audit table (optional)
```

---

## 3. Prerequisites

- Python 3.11+
- A **public** GitHub account and repository
- TradingView account (any plan supports Pine Script custom indicators)
- Optional: GitHub Actions (free tier is sufficient)

---

## 4. Setup Instructions

### Step 1 — Fork and clone this repository

```bash
# On GitHub: fork this repository
git clone https://github.com/YOUR_USERNAME/sunrise-seed-data.git
cd sunrise-seed-data
```

### Step 2 — Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 3 — Run the first manual fetch

```bash
python run_daily_update.py
```

This will:
- Fetch the last 12 days of sunrise data from timeanddate.com
- Run the astronomical cross-check
- Write CSV files to `data/`
- Save validated records to `validated/sunrise_records.json`

Check the output for any errors. If timeanddate.com is unreachable, existing CSV files are preserved and the script exits with code 1.

### Step 4 — Commit and push the CSV files

```bash
git add data/ validated/ logs/
git commit -m "Initial sunrise data"
git push origin main
```

The repository must be **public** for TradingView's `request.seed()` to access it.

### Step 5 — Add the Pine Script indicator to TradingView

1. Open TradingView
2. Open the Pine Script Editor (bottom of chart)
3. Paste the full contents of `confirmed_sunrise_zones.pine`
4. Click "Add to chart"
5. **Switch your chart to a 1-minute timeframe** (the indicator will error on other timeframes)

### Step 6 — Configure the GitHub repo in indicator settings

1. Click the indicator's settings gear icon
2. Under "Data Source", set the GitHub Repo field to: `YOUR_USERNAME/sunrise-seed-data`
3. Click OK

The indicator will start reading your seed data. Due to TradingView's cache (10-15 min TTL), it may take up to 15 minutes after a push for new data to appear.

---

## 5. Daily Update Mechanism

### GitHub Actions (Automated)

The file `.github/workflows/update_sunrise.yml` schedules the Python service to run 4 times daily:

| Run time | Purpose |
|---|---|
| 00:00 UTC | Tokyo sunrise is typically 20:00-22:00 UTC previous day (already past) |
| 06:00 UTC | Catches London sunrise (typically 04:00-08:00 UTC) |
| 12:00 UTC | Catches NYC sunrise (typically 10:00-14:00 UTC) |
| 18:00 UTC | Cleanup and re-verification run |

Each run: fetches -> validates -> cross-checks -> writes CSVs -> commits (if changed) -> pushes.

### Manual Update

```bash
python run_daily_update.py
git add data/ && git commit -m "Update $(date -u)" && git push
```

### Force Re-fetch

```bash
FORCE_REFETCH=true python run_daily_update.py
```

---

## 6. How Data Flows

1. **timeanddate.com** serves HTML pages with sunrise times
2. **sunrise_fetcher.py** scrapes the daily page (seconds precision) or monthly table (minute precision)
3. The fetcher converts local sunrise time to UTC using IANA timezone identifiers (handling DST automatically)
4. **astral_crosscheck.py** independently calculates sunrise and compares the delta
5. **seed_generator.py** encodes each confirmed sunrise into OHLCV CSV format:
   - `time` column = UTC milliseconds of the 1-minute candle open (candle that contains the sunrise)
   - `open` column = HHMM integer (e.g., 522 for 05:22)
   - `high` column = seconds (e.g., 37)
   - `low`  column = YYYYMMDD integer (e.g., 20260914)
   - `close` column = status code (1=VERIFIED, 2=WARNING)
6. **TradingView `request.seed()`** reads the CSV and returns non-`na` values on the exact bar where the sunrise candle is
7. The **Pine Script indicator** reads the bar's actual `high` and `low` values to draw the wick-to-wick zone box

---

## 7. Known Limitations

| Limitation | Detail |
|---|---|
| Pine cannot fetch from timeanddate.com | No HTTP requests from Pine Script. External Python service is required. |
| request.seed() cache TTL ~10-15 min | New data takes up to 15 minutes to appear after a push. Not an accuracy issue. |
| Monthly table: minute precision only | The monthly HTML table gives HH:MM, not HH:MM:SS. The daily page may give seconds. |
| Seed repo must be public | GitHub repository must be public for request.seed() to work. |
| 1-minute candle may not exist | On equity charts with session gaps, sunrise candles during market-closed hours won't exist. Recommend 24-hour symbols (e.g., EUR/USD). |
| Cloudflare protection | timeanddate.com uses Cloudflare WAF. High-frequency requests may be blocked. The service runs at most 4x daily with 1.5s delays between requests. |
| Scraping ToS | timeanddate.com's ToS prohibits automated scraping for commercial use. For production use, consider their commercial API at services.timeanddate.com. |

---

## 8. Troubleshooting

### "Sunrise data unavailable" in logs
timeanddate.com was unreachable. Existing CSV files are preserved. Check your internet connection and try again.

### HTML structure changed (CRITICAL log)
timeanddate.com redesigned their page. The scraper needs updating. Check `table#as-monthsun` selector. Do NOT use old data.

### request.seed() returns all na
- Verify the GitHub repo is public
- Verify the CSV files are in the `data/` folder
- Verify the CSV filenames match exactly: `SUNRISE_TOKYO.csv`, `SUNRISE_LONDON.csv`, `SUNRISE_NYC.csv`
- Wait 15 minutes for TradingView cache to expire

### "requires a 1-minute chart" error
Switch your chart to the 1M timeframe. This indicator only works on 1-minute charts.

### Cross-check FAIL warnings
The independent astral calculation differs by >120 seconds from timeanddate. This may indicate:
- A parsing error in the scraper
- timeanddate.com page structure change
- DST ambiguity (extremely rare)
Check `validated/sunrise_records.json` for details.

---

## 9. Manual Verification

To verify a displayed zone against timeanddate.com:

1. Note the zone's city and the candle timestamp from the diagnostic table
2. Open the timeanddate.com page for that city and date:
   - Tokyo: `https://www.timeanddate.com/sun/japan/tokyo?month=M&year=YYYY`
   - London: `https://www.timeanddate.com/sun/uk/london?month=M&year=YYYY`
   - New York: `https://www.timeanddate.com/sun/usa/new-york?month=M&year=YYYY`
3. Find the row for the specific date
4. Compare the displayed sunrise time to the zone's source time in the diagnostic table
5. On the TradingView chart, find the marked 1-minute candle
6. Verify: `box TOP = candle HIGH`, `box BOTTOM = candle LOW`
7. Verify: the candle's UTC timestamp matches the encoded `candle_open_utc_ms` in the CSV

---

## 10. Data Schema

```
CSV column  | Type    | Description
------------|---------|--------------------------------------------------
time        | int     | UTC milliseconds of the 1-minute candle open
            |         | (sunrise time floored to minute boundary)
open        | int     | HHMM integer: hour*100 + minute (e.g. 522 = 05:22)
high        | int     | Seconds component (e.g. 37)
low         | int     | YYYYMMDD integer (e.g. 20260914)
close       | int     | Status: 1=VERIFIED, 2=WARNING, 0=UNAVAILABLE
volume      | int     | 0 (reserved for future use)
```

Example row (Tokyo, 2026-09-14, sunrise at 05:22:37 JST):
```csv
time,open,high,low,close,volume
1757801520000,522,37,20260914,1,0
```

Decoding:
- `time=1757801520000` -> 2026-09-14 20:22:00 UTC (which is 2026-09-14 05:22:00 JST = correct!)
- `open=522` -> 05:22 local time
- `high=37` -> :37 seconds
- `low=20260914` -> local date 2026-09-14
- `close=1` -> VERIFIED