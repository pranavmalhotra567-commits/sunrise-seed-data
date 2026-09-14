# Manual Verification Guide

This guide provides step-by-step procedures to verify every displayed zone against the authoritative source (timeanddate.com) and confirm all system accuracy claims.

---

## 1. Verifying a Zone Against timeanddate.com

### Step 1 — Enable the Diagnostic Table

1. Click the indicator settings gear
2. Under "Diagnostics", enable "Show Diagnostic Audit Table"
3. The table appears in the top-right of the chart

### Step 2 — Read the Zone Record

From the diagnostic table, note for the zone you want to verify:
- **City** (e.g., TOKYO)
- **Local Date** (e.g., 2026-09-14)
- **Source Time** (e.g., 05:22:37)
- **UTC Candle** (e.g., 2026-09-13 20:22 UTC)
- **Status** (should be VERIFIED)

### Step 3 — Open timeanddate.com

Navigate to the city's monthly sun page for that date:
- **Tokyo:** `https://www.timeanddate.com/sun/japan/tokyo?month=9&year=2026`
- **London:** `https://www.timeanddate.com/sun/uk/london?month=9&year=2026`
- **New York:** `https://www.timeanddate.com/sun/usa/new-york?month=9&year=2026`

### Step 4 — Find the Date Row

In the table labeled "Sunrise & Sunset in [City]", find the row for the date.

### Step 5 — Compare Values

| What to compare | Expected match |
|---|---|
| Sunrise column on timeanddate.com | Matches "Source Time" in diagnostic table (may differ in seconds if monthly table was used) |
| Local date | Matches "Local Date" in diagnostic table |

**If the times differ by a few seconds:** The diagnostic table may show seconds from the daily page scrape, while the monthly table shows only minutes. Both identify the same 1-minute candle.

**If the times differ by more than 1 minute:** Investigate — check `validated/sunrise_records.json` and `logs/fetch_log.jsonl`.

### Step 6 — Verify the Candle on TradingView

1. On the 1-minute chart, find the candle matching the "UTC Candle" timestamp
2. Change your chart timezone to UTC if needed to read the timestamp
3. Hover over the zone box to confirm it's on the correct candle

### Step 7 — Verify Zone Geometry

1. Hover over the sunrise zone box
2. Note the zone's top (high) and bottom (low) prices
3. Read the candle's actual high and low values by hovering over the candle
4. **Confirm: box top = candle HIGH, box bottom = candle LOW**

---

## 2. Verifying Timezone Handling

### Procedure

1. Note the UTC candle timestamp from the diagnostic table (e.g., "2026-09-13 20:22 UTC")
2. Convert to local time using the correct timezone and DST rule:

```
Tokyo (always JST = UTC+9, no DST):
  2026-09-13 20:22 UTC + 9h = 2026-09-14 05:22 JST  ✓

London (BST = UTC+1 in summer):
  Example summer (June): 2026-06-15 03:49 UTC + 1h = 2026-06-15 04:49 BST  ✓
  Example winter (Jan):  2026-01-15 07:58 UTC + 0h = 2026-01-15 07:58 GMT  ✓

New York (EDT = UTC-4 in summer):
  Example summer (June): 2026-06-15 09:28 UTC - 4h = 2026-06-15 05:28 EDT  ✓
  Example winter (Jan):  2026-01-15 12:17 UTC - 5h = 2026-01-15 07:17 EST  ✓
```

3. Confirm the local time matches the "Source Time" in the diagnostic table.

---

## 3. Chart Timezone Test Procedure

This test verifies that changing the chart display timezone does NOT change which candle is selected.

### Setup
- Open a 1-minute chart with a confirmed sunrise zone visible
- Note the exact candle that is marked (by bar index or candle open time)

### Test Steps

1. **Set chart timezone to UTC**
   - Chart settings → Timezone → UTC
   - The zone box should remain on the same candle
   - The candle open time displays as UTC (e.g., "20:22")

2. **Set chart timezone to America/New_York**
   - The zone box must remain on the **same physical candle**
   - The timestamp label now shows New York local time (e.g., "16:22" = 4:22 PM)
   - The box itself does not move

3. **Set chart timezone to Asia/Tokyo**
   - Same candle, now shows Tokyo local time (e.g., "05:22" next day)
   - Box does not move

4. **Set chart timezone to Europe/London**
   - Same candle, now shows London local time
   - Box does not move

### Pass Criteria
The zone box must be on **exactly the same candle** in all 4 timezone settings. Only the displayed time changes.

### Why This Works
The Pine Script uses `xloc.bar_index` for box placement, which is timezone-independent. The seed data encodes UTC milliseconds, which are absolute. No display timezone affects candle selection.

---

## 4. DST Transition Test Procedure

### London (2026: clocks spring forward March 29 at 1:00 AM GMT → 2:00 AM BST)

1. Find the London sunrise zone for **March 28, 2026** (last GMT day)
2. Note the UTC candle time — should be close to 06:XX UTC (sunrise ~06:XX GMT)
3. Find the London sunrise zone for **March 29, 2026** (first BST day)
4. Note the UTC candle time — should be close to 05:XX UTC (sunrise ~06:XX BST = 05:XX UTC)

**Pass:** The March 29 zone's UTC time is approximately 1 hour earlier than March 28's UTC time, even if both show similar local sunrise times.

### New York (2026: clocks spring forward March 8 at 2:00 AM EST → 3:00 AM EDT)

1. Find the NYC sunrise zone for **March 7, 2026** (last EST day)
2. Note the UTC candle time — sunrise ~06:56 EST = 11:56 UTC
3. Find the NYC sunrise zone for **March 8, 2026** (first EDT day)
4. Note the UTC candle time — sunrise ~06:55 EDT = 10:55 UTC (roughly)

**Pass:** March 8 UTC time is approximately 1 hour earlier than March 7, reflecting the DST change.

### Tokyo (no DST — always UTC+9)

1. Find Tokyo zones across multiple months
2. Verify UTC = local - 9 hours consistently
3. No seasonal variation in the UTC offset

---

## 5. Verifying the Data Source

### Check the Log File

```bash
# Show last 20 fetch operations
tail -n 20 logs/fetch_log.jsonl

# Show all CRITICAL errors
grep "CRITICAL" logs/fetch_log.jsonl

# Show source URLs used
grep "Fetching" logs/fetch_log.jsonl
```

### Check Validated Records

```bash
# Show all confirmed records with source URLs
python -c "
import json
with open('validated/sunrise_records.json') as f:
    records = json.load(f)
for r in records:
    print(f\"{r['city']:8} {r['local_date']} {r['local_sunrise']} | {r['source']} | {r['source_url'][:60]}\")
"
```

### Check Cross-Check Results

```bash
python -c "
import json
with open('validated/sunrise_records.json') as f:
    records = json.load(f)
for r in records:
    xr = r.get('crosscheck', {}) or {}
    status = xr.get('status', 'N/A')
    delta = xr.get('delta_seconds', -1)
    calc = xr.get('calculated', 'N/A')
    print(f\"{r['city']:8} {r['local_date']} | source={r['local_sunrise']} | calc={calc} | delta={delta}s | {status}\")
"
```

---

## 6. Verifying the Acceptance Criteria (spec section 35)

For each displayed zone, verify all 15 criteria:

| # | Criterion | How to Verify |
|---|---|---|
| 1 | Came from timeanddate.com | Check `source_url` in `validated/sunrise_records.json` |
| 2 | Sunrise had already occurred | Check `confirmation_status == CONFIRMED` in records |
| 3 | Source timestamp preserved | Compare `local_sunrise` in record to timeanddate.com page |
| 4 | Timezone correctly interpreted | Follow procedure in section 2 above |
| 5 | DST correctly handled | Follow DST test in section 4 above |
| 6 | Absolute timestamp correct | Convert UTC ms to local time; must match source |
| 7 | Exact 1-minute candle found | Verify candle open time matches `candle_open_utc_ms // 60000 * 60000` |
| 8 | Box top = candle HIGH | Hover over zone and compare to candle high |
| 9 | Box bottom = candle LOW | Hover over zone and compare to candle low |
| 10 | Box begins at that candle | Zone left edge is on the sunrise candle |
| 11 | Box extends rightward | Visual check: zone extends to chart right edge |
| 12 | Correct city color | Tokyo=red, London=green, NYC=blue (defaults) |
| 13 | No future sunrise displayed | Enable diagnostics; all status = CONFIRMED |
| 14 | No nearest-candle approximation | Seed timestamp IS the candle open time (exact match) |
| 15 | No invalid data substituted | All zones have source=timeanddate.com in audit table |