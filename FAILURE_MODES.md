# Failure Mode Documentation

This document describes every known failure mode, the system's behavior in each case, user-visible effects, and recovery procedures. The system prioritizes accuracy over availability — it is always better to show nothing than to show incorrect data.

---

## 1. timeanddate.com Unreachable (HTTP Error)

**Trigger:** Network error, DNS failure, 5xx HTTP response, Cloudflare block (403/429)

**Python service behavior:**
- `_get()` retries 3 times with exponential backoff
- After 3 failures: `logger.critical("All 3 attempts failed...")` 
- `fetch_sunrise()` returns `None`
- `run_daily_update.py` logs "timeanddate.com unreachable — no data invented"
- Script exits with code 1
- **Existing CSV files are NOT modified** (last valid state is preserved)

**User-visible effect (TradingView):**
- No new zones appear after the 12-day rolling window expires
- Existing zones within the window remain intact
- Info table shows the last zone count

**Recovery:**
1. Check GitHub Actions workflow logs
2. Test connectivity: `curl -I https://www.timeanddate.com/sun/japan/tokyo`
3. If Cloudflare blocked: wait 30-60 minutes, retry
4. Trigger manual update: GitHub Actions → Run workflow → force_refetch=false

---

## 2. timeanddate.com HTML Structure Changed

**Trigger:** timeanddate.com redesigns their page, renames the table ID, changes DOM structure

**Python service behavior:**
- `_parse_monthly_table()` cannot find `table#as-monthsun`
- Logs `CRITICAL: HTML STRUCTURE CHANGED: table#as-monthsun not found`
- Returns `None` — NEVER guesses or uses partial data
- Existing CSVs preserved

**User-visible effect (TradingView):**
- No new zones added after existing ones expire from the 12-day window
- No incorrect data is ever displayed

**Recovery:**
1. Check logs for CRITICAL messages
2. Inspect the timeanddate.com page HTML in a browser
3. Update the CSS selector in `_parse_monthly_table()` to match new structure
4. Re-run `run_daily_update.py` after fixing the parser
5. Update `_parse_daily_page()` if daily page structure also changed

**Note:** This is the most important failure to catch. The system fails loudly rather than silently parsing wrong data.

---

## 3. GitHub Actions Workflow Failure

**Trigger:** GitHub Actions quota exceeded, workflow YAML syntax error, Python dependency install failure

**Effect:**
- No daily update runs
- Existing CSV files remain unchanged
- Zones in the 12-day window still display correctly
- New confirmed sunrises are not added until the workflow runs again

**Recovery:**
1. Check GitHub Actions tab for error details
2. For dependency errors: fix `requirements.txt` and push
3. For quota: wait until quota resets (monthly)
4. Manually run: `python run_daily_update.py && git add data/ && git commit -m "Manual update" && git push`

---

## 4. GitHub Repository Unavailable

**Trigger:** Repository made private, repository deleted, GitHub outage

**Pine Script behavior:**
- `request.seed(..., ignore_invalid_symbol=true)` returns `na` for all bars
- No zones are drawn
- Setup warning may appear if `i_github_repo` becomes invalid
- Info table shows "0 / 36 active zones"

**Recovery:**
1. Ensure the repository is public
2. Verify the repository name in indicator settings matches exactly

---

## 5. request.seed() Returns All na

**Triggers:**
- Repository not yet set up (placeholder username)
- Cache not yet expired after first push
- CSV file naming mismatch
- Repository just made public (takes time for TradingView to index)

**Pine Script behavior:**
- No zones drawn
- Setup warning displayed if placeholder repo detected
- Info table shows "0 / 36 active zones"

**Recovery:**
1. Wait 15 minutes for TradingView cache to expire
2. Verify CSV filenames are exactly: `SUNRISE_TOKYO.csv`, `SUNRISE_LONDON.csv`, `SUNRISE_NYC.csv`
3. Verify CSV files are in the `data/` subdirectory
4. Try refreshing the chart (F5 or re-adding the indicator)
5. Verify the CSV content is valid (not empty, correct header)

---

## 6. 1-Minute Candle Doesn't Exist for Sunrise Time

**Trigger:** The chart symbol has a session gap during the sunrise time (e.g., US equity chart, pre-market hours)

**Behavior:**
- The seed data timestamp is correct
- TradingView cannot attach seed data to a non-existent bar
- `request.seed()` returns `na` on those bars
- No zone is drawn for that city/date
- **No fallback to nearest candle** — the zone simply doesn't appear

**Effect:**
- Status in `validated/sunrise_records.json` shows CONFIRMED
- But TradingView never draws the zone because the bar doesn't exist

**Recommendation:**
- Use a 24-hour symbol for full coverage:
  - Forex: EUR/USD, GBP/USD, USD/JPY
  - Crypto: BTC/USDT (Binance, Coinbase)
  - US equity ETFs with extended hours

---

## 7. Astronomical Cross-Check Failure (delta > 120s)

**Trigger:** timeanddate.com value differs from astral calculation by more than 120 seconds

**Python service behavior:**
- Record is written to CSV with status code 2 (WARNING)
- Log entry: `"Cross-check FAIL: tokyo 2026-09-14 | source=05:22 | calc=05:24 | delta=120s"`
- **The timeanddate value is preserved** — never replaced by astral value
- `run_daily_update.py` exits with code 2 (partial failure)

**User-visible effect (TradingView):**
- Zone drawn with WARNING status (orange in diagnostic table)
- Zone geometry is based on the timeanddate value (as specified)

**Action required:**
- Review `validated/sunrise_records.json` for the flagged record
- Manually verify against timeanddate.com
- If timeanddate value is clearly wrong, contact timeanddate or wait for correction

---

## 8. Future Sunrise Passes Validation (Defense-in-Depth)

**Trigger:** Logic error in the service — a future sunrise somehow isn't caught

**Defense layers:**
1. Python: `is_confirmed()` checks `utc_timestamp_ms < time.time() * 1000`
2. Python: `confirmation_status` is never set to CONFIRMED for future records
3. Python: `seed_generator.py` re-checks `utc_timestamp_ms < time.time() * 1000` before writing
4. Pine Script: `time >= timenow` guard in `create_zone()`

**It would take failures at ALL FOUR layers for a future zone to appear.** The probability is effectively zero under normal operation.

---

## 9. DST Timezone Data Error

**Trigger:** pytz library has stale DST data (extremely rare; pytz is updated regularly)

**Detection:**
- Cross-check delta would be large (3600 seconds = 1 DST hour) during DST transition periods
- `validation_status = "FAIL"` for affected records

**Prevention:**
- `requirements.txt` pins `pytz>=2024.1` with a recent DST database
- GitHub Actions installs fresh dependencies on each run

---

## 10. CSV Format Corruption

**Trigger:** Partial write, encoding error, disk error during CSV generation

**Detection:**
- Python's `csv` module will raise an exception on malformed files
- `seed_generator.py` writes atomically (complete file before closing)

**Pine Script behavior:**
- Corrupted CSV causes `request.seed()` to return `na` (not crash)
- With `ignore_invalid_symbol=true`, no fatal error

**Recovery:**
1. Delete the corrupted CSV from `data/`
2. Run `FORCE_REFETCH=true python run_daily_update.py`

---

## 11. Rolling Window Miscalculation

**Trigger:** Logic error in date comparison

**Safeguard:**
- Python (`seed_generator.py`): `city_records[-max_days:]` slices to last 12
- Pine Script (`enforce_rolling_window()`): collects unique dates, sorts descending, keeps top 12
- Both enforce the limit independently

---

## 12. TradingView Box Limit Exceeded

**Trigger:** More than 50 boxes created (shouldn't happen with 36 max, but guarded)

**Protection:**
- `max_boxes_count=50` declared in indicator()
- `enforce_rolling_window()` deletes expired boxes before TradingView's FIFO kicks in
- We never create more than 36 boxes (3 cities × 12 days)

---

## 13. Chart Symbol Has No 1-Minute Candle for Sunrise Time

**This is the same as failure mode 6**, specialized for the case where you know the symbol covers 24 hours but there's a specific gap (e.g., exchange maintenance window).

**Example:** Binance BTC/USDT may have a 1-minute gap during scheduled maintenance windows.

**Behavior:** Zone simply doesn't appear. No error. No fallback.

**Diagnostic:** Enable the audit table to see which zones are CONFIRMED in the data but not visible on the chart.