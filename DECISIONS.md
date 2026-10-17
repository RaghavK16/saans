# Decision log

Every meaningful product or technical decision: the context, the options considered, what we
chose, why, and what would make us revisit it. Newest last. Statuses: **Accepted**,
**Proposed** (default applied, waiting on confirmation), **Pending** (needs a choice),
**Superseded** (link to the replacement).

---

## D-001 · Use India's CPCB NAQI, not US AQI
*2026-10-18 · Accepted · Owner: user*

**Context.** Most free AQI APIs (WAQI, Open-Meteo's `us_aqi`) report the US EPA scale. Indian
health advisories, the CPCB bulletin and IITM forecasts use NAQI, which has different
breakpoints and categories. The same air can read as "Unhealthy" in the US index and
"Moderate" in NAQI.
**Options.** (a) Show US AQI as provided. (b) Show both. (c) Compute NAQI ourselves from
concentrations.
**Decision.** (c). Third-party AQI numbers are never shown raw.
**Why.** The brief has to agree with the official numbers the user sees in Delhi news and
advisories, and the scorecard has to compare like with like.
**Revisit if.** CPCB revises the NAQI breakpoints.

## D-002 · Hourly outlook: official rolling NAQI *and* an "instant" hourly index
*2026-10-18 · Proposed (default applied; the user delegated it)*

**Context.** Official NAQI uses 24 h averages for PM2.5/PM10/NO₂/SO₂/NH₃ and 8 h for CO/O₃.
An hourly value computed that way lags real conditions by up to a day, which is useless for
"can I train outdoors at 8 pm?".
**Options.** (a) Official rolling only: faithful but laggy. (b) "Instant": NAQI breakpoints
applied to hourly concentrations, actionable but not an official number. (c) Both, each in its
own place.
**Decision.** (c). Official NAQI for headlines and the scorecard (comparable with CPCB/IITM).
Instant NAQI for timing decisions (workout, windows, commute), always labelled "instant".
**Why.** Each question needs a different number. Labelling them stops the brief from appearing
to contradict the CPCB bulletin.
**Revisit if.** The user finds two numbers confusing in practice.

## D-003 · Manual runs for now, with no background schedule
*2026-10-18 · Accepted · Owner: user*

**Context.** The original brief asked for a launchd collector. The user chose to run Saans
manually ("only when I run an execution").
**Options.** (a) launchd every hour. (b) Manual `saans run`. (c) Manual now, cloud schedule later.
**Decision.** (c): one command, `saans run`, does collect → store → brief. A launchd template ships
in `ops/` but isn't installed.
**Consequences (accepted knowingly).**
- **Lost for good** on days we don't run: Open-Meteo AQ forecasts (no previous-runs archive
  for air quality; tested), the data.gov.in station snapshot (latest only), WAQI and IITM forecasts.
- **Recoverable**: each run catches up on the CPCB bulletin (by date), FIRMS (by date),
  Open-Meteo weather (previous runs), and OpenAQ (history, Phase 2).
- Without a schedule we get one snapshot a day, not 24 hourly ones. Official 24 h NAQI for
  scoring is still possible from OpenAQ hourly history and the bulletin.
**Mitigation.** Run log records the gap since the last run, and the brief shows a "data health" line.
**Revisit if.** The scorecard has too many holes, or when we move online (D-006).

## D-004 · Raw-first storage: immutable files plus a SQLite index
*2026-10-18 · Accepted*

**Context.** This season's data is the valuable part. Parsers will have bugs, and a later model
needs features we haven't thought of yet.
**Options.** (a) Parse on fetch, keep only clean rows. (b) Raw bodies as SQLite BLOBs.
(c) Raw files in `data/raw/<source>/<date>/…` (gzipped) with an index table in SQLite.
**Decision.** (c). All parsed tables are derived from raw and can be rebuilt (`saans reparse`).
**Why.** Fixing a parser never loses history. Files are easy to inspect, and they map directly onto
object storage when the project goes online. The DB stays small. Recorded raw responses also make
the test fixtures realistic.
**Revisit if.** The raw archive grows beyond a few GB (unlikely: about 0.5 MB/day, mostly PDFs).

## D-005 · Public GitHub repo: what is and isn't published
*2026-10-18 · Accepted*

**Context.** The repo will be public (portfolio). It holds a single user's routine and locations,
and some sources restrict redistribution.
**Decision.**
- `.env` (keys), `data/` (DB + raw archive) and `out/` (briefs) are gitignored.
- `config.yaml` holds **locality-level** coordinates only (rounded to 0.01°, ~1 km): never an
  address or building.
- Test fixtures are small, scrubbed samples. No WAQI responses are committed, because WAQI's terms
  forbid redistributing cached or archived data. Synthetic fixtures are used for WAQI instead.
- URLs are logged with keys stripped.
**Why.** Portfolio visibility without leaking secrets or personal data, and without breaching terms.
**Note.** Creating the GitHub repo and pushing are done only when the user explicitly says so.

## D-006 · Platform-neutral core, so it can move online later
*2026-10-18 · Accepted*

**Context.** The user plans to host Saans as a site later.
**Decision.** All logic is behind a CLI (`saans run`). No macOS-specific code in the package.
Scheduling (launchd now, cron or GitHub Actions later) and delivery are adapters. SQLite now,
with plain SQL so a Postgres move is mechanical.
**Why.** Moving online should mean adding a host and a scheduler, not a rewrite.
**Revisit if.** We choose a hosting platform with strong opinions (e.g. serverless with no disk).

## D-007 · Phase order: plan → stubble warning → scorecard
*2026-10-18 · Accepted*

**Context.** The original priority order was daily plan, stubble warning, scorecard.
Stubble burning peaks roughly late October to mid November, which is now.
**Options.** (a) Scorecard before stubble. (b) Stubble before scorecard.
**Decision.** (b). The scorecard's *inputs* are collected from Phase 1 onward, so scoring later
loses nothing, while an early-warning feature built after the season is over is worth little this year.
**Revisit if.** Phase 2 runs long and the season is ending; then skip ahead to Phase 4.

## D-008 · Tooling: venv + pip, httpx, respx, pytest-socket
*2026-10-18 · Accepted*

**Options.** `uv` (faster, but needs an install script on this Mac) vs. built-in `venv` + `pip`.
`requests` + `responses` vs. `httpx` + `respx`.
**Decision.** `venv` + `pip` + `pyproject.toml`. `httpx` (timeouts and retries as first-class
features, async later if needed) with `respx` for mocking. `pytest-socket` to *prove* tests are
offline.
**Why.** Nothing extra to install, and an SDET-friendly guarantee that tests never hit live APIs.

## D-009 · v1 source roles
*2026-10-18 · Accepted (see DATA_SOURCES.md for the evidence)*

| Need | Primary | Backup / later |
|---|---|---|
| Hourly forecast at a point | Open-Meteo AQ (CAMS) | WAQI forecast |
| Observed now (stations) | CPCB via data.gov.in | WAQI, OpenAQ |
| Observed history (concentrations) | OpenAQ (coverage to be verified) | — |
| Official ground truth, city daily | CPCB 4 PM bulletin (PDF) | — |
| Official forecast | IITM AQEWS (scraped, best effort) | IMD city bulletin PDF |
| Fires | NASA FIRMS VIIRS (SNPP, NOAA-20, NOAA-21) | MODIS |
| Wind / mixing | Open-Meteo Weather + Previous Runs | — |

**Notable findings that shaped this.** data.gov.in values appear to be sub-indices, not
concentrations. Open-Meteo AQ can't backfill forecasts. CPCB bulletins are fetchable back to at least
2025-11-01, which enables a backtest on last season. IITM is unreachable from the user's network
about half the time.

## D-010 · Routine model
*2026-10-18 · Proposed (defaults derived from the user's answers)*

- **Workout:** two candidate slots, 08:00–09:00 and 20:00–21:00. The choice is outdoors near home
  vs. the local gym (indoor). Default thresholds: outdoors if instant NAQI ≤ 100 for the whole slot;
  outdoors but lighter/shorter at 101–150; gym above 150.
- **Office:** any 3 days a week, hours 11:00–17:00. Commute options are evaluated for leaving
  home 09:00–10:30 and leaving the office 16:30–18:30. Saans also suggests the 3 best office days
  from the multi-day forecast.
- **Route (default, editable):** Model Town → ISBT Kashmere Gate → Ring Road (ITO) → DND → Noida.
  The office sector is a placeholder until the user sets it in `config.yaml`.
- **Windows open** only when instant NAQI ≤ 100. Purifier runs otherwise.
**Revisit if.** The user corrects any of it. All of these values live in `config.yaml`, not code.

---

## Pending

### P-001 · Push channel for the brief
*Needed by Phase 2*

| | Telegram bot | Email | Google Calendar events |
|---|---|---|---|
| Setup | Create a bot via @BotFather, get chat id (~5 min) | SMTP + Gmail app password (needs 2FA) | Google Cloud project + OAuth consent |
| Phone experience | Instant push, readable on the lock screen | Lands in an inbox; easy to ignore | Time blocks ("Run outside 20:00", "Leave 09:40") with reminders |
| Fits "what to do today" | Good | OK | Excellent for windows, poor for explanations |
| Fails when | Telegram unavailable | Spam filters | Event duplication/updates are fiddly |
| Moves online | Trivially (one HTTPS call) | Easy | Needs token refresh handled on the server |
| Cost | Free | Free | Free |

**Recommendation:** Telegram, because it's the least setup, most glanceable, and easiest to host
later. Calendar is the most interesting product-wise and could come later as a second channel.
