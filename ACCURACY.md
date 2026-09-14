# Accuracy / Validation Report

## What This Report Covers

This report documents what has been verified, what TradingView technically guarantees, what depends on the external data source, and what limitations remain. It does not claim "100% perfect" — it reports honestly.

---

## 1. What Has Been Verified

| Claim | Verification Method | Result |
|---|---|---|
| timeanddate.com is the source | Source URL stored in `SunriseRecord.source_url` | Traceable per record |
| Sunrise has already occurred | `is_confirmed()` checks `utc_timestamp_ms < time.time() * 1000` | Enforced in Python + Pine |
| Source time is preserved | `local_sunrise` field stored verbatim from HTML parse | Not rounded |
| IANA timezone used (not offset) | `pytz.timezone(iana_str)` with full DST database | Verified |
| DST handled automatically | pytz `localize()` with `is_dst=None` | Tested on DST transition dates |
| Candle selection correct | `candle_open_utc_ms = floor(utc_ms to minute)` | Exact candle boundary math |
| Box HIGH = candle HIGH | Pine reads `high` of the matched bar | Native Pine value |
| Box LOW = candle LOW | Pine reads `low` of the matched bar | Native Pine value |
| Box begins at candle | `box.new(left=bar_index, ...)` | Exact candle index |
| Box extends rightward | `extend=extend.right` | Pine built-in |
| City color correct | Separate color inputs per city | Fully independent |
| No future sunrise displayed | Double-guarded: Python + Pine | Belt-and-suspenders |
| No nearest-candle substitution | Seed data timestamp IS the candle open time | Exact match |
| No silent data substitution | Returns None + logs error if source fails | Verified |

---

## 2. TradingView Platform Guarantees

### What TradingView Guarantees

- `request.seed()` returns `na` if the repository/file doesn't exist
- When `request.seed()` returns non-`na` on a bar, that bar's `time` contains the seed's timestamp
- `bar_index`, `high`, `low`, `time` are accurate for the 1-minute bar
- `extend.right` accurately extends the box to the chart's right edge
- `timeframe.isminutes and timeframe.multiplier == 1` correctly identifies 1-minute charts
- `runtime.error()` halts script execution with a visible error message

### What TradingView Does NOT Guarantee

- Cache TTL for `request.seed()` is approximately 10-15 minutes (not instant)
- There is no way to know exactly when TradingView refreshed the seed cache
- If the chart symbol has session gaps (equity), 1-minute bars may not exist during sunrise hours

---

## 3. External Data Dependencies

### Dependency: timeanddate.com

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Site unreachable | Low | No new zones until fixed | Cache preserves last valid data; script logs CRITICAL |
| HTML structure changed | Low-medium | Parser silently returns None; logs CRITICAL | Fail loudly, never guess |
| ToS enforcement | Low | IP blocked | Low request rate (1.5s delay, 3-4 fetches/day) |
| Data error | Extremely low | Wrong sunrise time | Astral cross-check catches if delta > 120s |

### Dependency: GitHub Actions

| Risk | Impact | Mitigation |
|---|---|---|
| Workflow failure | No daily update; zones become stale after 12 days | GitHub Actions notifications; manual trigger available |
| Repo becomes private | request.seed() fails | Keep repo public; documented in setup guide |

---

## 4. Known Limitations

### Precision Limitation

**Monthly HTML table:** minute precision only (HH:MM).
**Daily HTML page:** may have seconds precision (HH:MM:SS).

For candle selection:
- Minute precision is sufficient to identify the correct 1-minute candle in most cases
- Exception: if sunrise is at exactly HH:MM:59 (last second of a minute), minute precision from the table would show HH:MM but the actual sunrise is still in the HH:MM candle, so the result is still correct
- The only case where seconds matter for candle selection is distinguishing HH:MM:59 from HH:(MM+1):00 — both extreme edge cases that minute precision handles correctly because the minute component is the same

### Market Session Gap Limitation

If the chart symbol does not have 24-hour coverage (e.g., US equities), the 1-minute sunrise candle may not exist. The seed data timestamp is correct, but there is no corresponding bar on the chart. Pine Script's `request.seed()` will return `na` in this case because there is no bar to attach the data to. The zone will simply not appear.

**Recommendation:** Use a 24-hour symbol (e.g., EUR/USD, BTC/USD, SPY after-hours) for full coverage.

### TradingView Cache Delay

After the Python service pushes new CSV data to GitHub, TradingView takes approximately 10-15 minutes to refresh. This is a platform limitation. New sunrise zones may appear with up to 15-minute delay after the GitHub commit.

---

## 5. Cross-Check Methodology

The `astral` Python library provides an independent sunrise calculation using the same coordinates as timeanddate.com:

```
Tokyo:    35.6895°N, 139.6917°E, 40m elevation
London:   51.5085°N, 0.1257°W,   25m elevation
New York: 40.7143°N, 74.0060°W,  10m elevation
```

For each record:
1. `astral.sun.sun(observer, date=local_date, tzinfo=tz)["sunrise"]` computes sunrise
2. Delta = `|astral_result - timeanddate_result|` in seconds
3. PASS if delta <= 30s, WARNING if 31-120s, FAIL if > 120s

**Important:** A FAIL result flags the record with WARNING status (code 2) in the CSV. The timeanddate value is always preserved. The astral calculation is never substituted.

---

## 6. Precision Analysis

| Source | Precision | Impact on Candle Selection |
|---|---|---|
| timeanddate.com daily page | HH:MM:SS | Exact second available |
| timeanddate.com monthly table | HH:MM | Sufficient for correct candle identification |
| astral library | Sub-second | Used for cross-check only |

**Example:** Sunrise at 05:22:37

With second precision: `candle_open_utc_ms` = UTC ms for 05:22:00 → maps to the 05:22 candle ✓
With minute precision: `candle_open_utc_ms` = UTC ms for 05:22:00 → maps to the 05:22 candle ✓

Both give the same candle. Second precision provides a more accurate representation in the diagnostic table, but both correctly identify the 1-minute candle.

---

## 7. DST Accuracy

DST is handled at three levels:

| Level | Mechanism |
|---|---|
| Python (timeanddate parsing) | `pytz.timezone(iana).localize(datetime(...), is_dst=None)` |
| Python (astral cross-check) | `astral.sun.sun(..., tzinfo=pytz_tz)` |
| Pine Script | `timestamp("America/New_York", ...)` and `str.format_time(..., "America/New_York")` |

pytz's DST database covers all historical and current DST transitions. The `is_dst=None` parameter in `localize()` raises `pytz.exceptions.AmbiguousTimeError` during ambiguous transitions (e.g., clocks fall back), which the code handles gracefully by logging an error.

Sunrise times are almost always in the early morning and therefore never in ambiguous DST transition windows (which occur at 1:00-3:00 AM local time and don't affect sunrise in Tokyo, London, or New York).

---

## 8. Candle Selection Accuracy

**Candle selection logic:**

```
candle_open_utc_ms = floor(utc_sunrise_timestamp_ms / 60000) * 60000

The 1-minute candle containing the sunrise starts at:
  candle_open_utc_ms

and ends at:
  candle_open_utc_ms + 60000 (exclusive)

Therefore:
  candle_open_utc_ms <= utc_sunrise_timestamp_ms < candle_open_utc_ms + 60000

This is the exact candle defined by the spec (section 9).
```

The seed data `time` column stores `candle_open_utc_ms`, which is the candle open time. TradingView's `request.seed()` maps this timestamp to the bar whose `time` equals `candle_open_utc_ms`. When the seed data arrives on that bar, the Pine script reads that bar's `high` and `low` to draw the zone.

**Verification:** `high` and `low` on a Pine Script bar are the actual market data values for that 1-minute candle — they cannot be forged or approximated. The box therefore accurately represents the candle's wick-to-wick range.