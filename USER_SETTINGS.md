# User Settings Reference

All configurable settings for the Confirmed Sunrise Zones TradingView indicator.
Access via: **Indicator gear icon → Settings**

---

## Group: Data Source

| Setting | Type | Default | Description |
|---|---|---|---|
| **GitHub Repo** | String | `YOUR_GITHUB_USERNAME/sunrise-seed-data` | Your public GitHub repository containing the sunrise CSV files. Format: `username/repo-name`. |

**Setup:**
1. Fork this repository on GitHub
2. Set the repo to **public**
3. Run the Python data service at least once to populate `data/`
4. Enter your `username/repo-name` here
5. Allow 10-15 minutes for TradingView to cache the data

**Wrong value symptoms:** "Active Zones: 0 / 36" in the info table, no zones on chart.

---

## Group: Cities

| Setting | Type | Default | Description |
|---|---|---|---|
| **Show Tokyo** | Bool | ✓ | Toggle the Tokyo sunrise zone display |
| **Show London** | Bool | ✓ | Toggle the London sunrise zone display |
| **Show New York** | Bool | ✓ | Toggle the New York City sunrise zone display |

---

## Group: Colors

| Setting | Type | Default | Description |
|---|---|---|---|
| **Tokyo Color** | Color | `#E74C3C` (red) | Box border and fill color for Tokyo zones |
| **London Color** | Color | `#27AE60` (green) | Box border and fill color for London zones |
| **New York Color** | Color | `#2980B9` (blue) | Box border and fill color for New York zones |
| **Zone Fill Transparency** | Int 0–95 | `80` | 0 = fully opaque fill, 95 = nearly invisible fill |
| **Show Zone Border** | Bool | ✓ | Whether to draw a visible border around each zone box |
| **Border Width** | Int 1–3 | `1` | Thickness of the zone border in pixels |

**Transparency guidance:**
- `80` = light fill (recommended, readable with price action)
- `50` = medium fill
- `0` = solid fill (hides candlesticks)

---

## Group: Labels

| Setting | Type | Default | Description |
|---|---|---|---|
| **Show Labels** | Bool | ✓ | Toggle city name and time labels on each zone |
| **Label Size** | Enum | `small` | Text size: `tiny`, `small`, or `normal` |

Label text format: `CITY\nHH:MM[:SS]` (e.g., `TOKYO\n05:22:37`)

---

## Group: Diagnostics

| Setting | Type | Default | Description |
|---|---|---|---|
| **Show Diagnostic Audit Table** | Bool | ✗ | Shows a full audit table of all active zones in the top-right corner |

### Audit Table Columns

| Column | Content |
|---|---|
| City | TOKYO / LONDON / NEW YORK |
| Local Date | YYYY-MM-DD in city timezone |
| Source Time | HH:MM:SS or HH:MM from timeanddate.com |
| Timezone | IANA timezone identifier |
| UTC Candle | UTC timestamp of the matched 1-minute candle |
| Hi / Lo | Candle HIGH / LOW (zone geometry) |
| Status | VERIFIED (green), WARNING (orange), UNAVAILABLE (red) |

Enable this table when:
- Verifying a zone against timeanddate.com
- Debugging missing zones
- Confirming DST handling
- Auditing the source data for a specific date

---

## Info Table (Always Visible)

A small table in the bottom-right corner always shows:
- **Active Zones** — current count / maximum (36)
- **Repository** — the configured GitHub repo (orange if not set up)
- **Source** — always "timeanddate.com"

---

## Known Constraints

| Constraint | Detail |
|---|---|
| **Timeframe** | Only works on 1-minute charts. A `runtime.error()` fires on all other timeframes. |
| **request.seed() delay** | New data takes ~10-15 minutes to appear after a GitHub push |
| **Max zones** | 36 (3 cities × 12 days) — well within TradingView limits |
| **Chart symbol** | Must have 1-minute bars during sunrise hours. 24h symbols recommended (EUR/USD, BTC/USD) |
