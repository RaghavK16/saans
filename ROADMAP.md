# Roadmap

Each phase ships something usable and has a definition of "done" that can be checked.
The order and its reasoning are in [DECISIONS.md](DECISIONS.md) (D-007).

**Running Saans:** you run one command, `saans run`, and it collects, stores and writes
today's brief. There is no background schedule for now (D-003). Run it once every morning:
any day you skip loses that day's forecasts and station snapshot for good.

---

## Phase 0: Foundations ✅ (this commit)
- DATA_SOURCES.md (every source tested), ROADMAP.md, CLAUDE.md, DECISIONS.md, `.gitignore`.

**Done when:** these docs are committed and you've requested the two Phase 1 keys
(data.gov.in, NASA FIRMS).

---

## Phase 1: Collector + brief scaffold (start collecting history)
Goal: from your first `saans run`, store everything we'll ever need. Minimal brief.

1. Project skeleton: `pyproject.toml`, `saans/` package, `venv`, `config.yaml` (locations,
   routes, thresholds, schedule), `.env` / `.env.example` for keys.
2. Storage. The raw layer is immutable: every API response goes to `data/raw/` with an index row
   in SQLite (source, URL without secrets, params, fetched_at UTC, HTTP status, sha256, file path).
   Parsed tables can always be rebuilt from raw (`saans reparse`).
3. Collectors, ordered by how irreplaceable the data is:
   - Open-Meteo AQ forecast for home, office and 3 route points (no key)
   - Open-Meteo weather: wind and boundary layer for Delhi plus a grid over Punjab/Haryana (no key)
   - CPCB station snapshot via data.gov.in, Delhi + Noida (key)
   - NASA FIRMS VIIRS hotspots, Punjab + Haryana, plus catch-up for days since the last run (key)
   - CPCB daily bulletin PDFs: download every missing date, with a one-time backfill to
     2025-10-01. Store raw only; parsing comes in Phase 4.
4. `naqi.py`: CPCB NAQI sub-index and overall-index calculator. A pure function, table-driven,
   and the most heavily tested file in the project. Offers both "official" (24 h/8 h rolling)
   and "instant" (hourly) modes (D-002).
5. Run log: each run records which sources succeeded, failed or were skipped (missing key), and
   the gap since the last run.
6. Brief scaffold: `out/brief-YYYY-MM-DD.md` and `.html` containing today's hourly NAQI outlook
   for home and office, the latest observed AQI at the nearest stations, and the run's data-health line.
   No recommendations yet.
7. Tests: pytest with recorded fixtures (`tests/fixtures/`), network blocked in tests.
8. `ops/com.saans.run.plist`: a launchd template, **not installed** (for when you want a schedule).

**Done when:**
- On a fresh clone, `pip install -e '.[dev]' && saans run` with keys in `.env` writes raw files and
  index rows for every source, plus a brief file.
- Removing a key skips that source with a warning, and the run still finishes with exit code 0.
- `pytest` passes with Wi-Fi off. NAQI breakpoints are tested at every boundary for every pollutant.
- `saans reparse` rebuilds the parsed tables from raw and gives identical results.

## Phase 2: The daily plan (recommendations)
- Rules engine driven by thresholds in `config.yaml`. Every recommendation carries its *reason*
  ("8–9 pm instant NAQI 180–210 → gym").
  - **Workout:** compare the 8–9 am and 8–9 pm slots. Outdoors if instant NAQI stays ≤ 100 for the
    whole hour, outdoors but light/short at 101–150, gym above 150.
  - **Purifier / windows:** hours when windows can be opened (outdoor ≤ 100); purifier on otherwise;
    a "close up before" time when a spike is coming.
  - **Commute (on office days):** route NAQI for departures 09:00–11:00 → arrive by 11:00, and 16:30–18:30
    for the return. Pick the least-bad window and say when to switch recirculation on
    (default: the whole trip if route NAQI > 100), plus a reminder to let in fresh air about every
    20–30 min to stop CO₂ building up in the cabin.
  - **Office-day picker:** "best 3 office days this week" from the multi-day forecast. You go in
    any 3 days a week, so this is a cheap, high-value suggestion.
- Add the OpenAQ collector (station concentrations with history, which also backfills missed
  days) and the WAQI collector.
- **Push channel:** build the one you pick (see DECISIONS.md, P-001).

**Done when:** the brief answers "train outside? when to air out the house? when to leave and
when to recirculate? which days to go in?", each with a reason, and scenario tests (clean day,
smog day, mixed day, missing data) pass.

## Phase 3: Stubble-fire early warning (heuristic v1)
Built before the scorecard because peak burning season (roughly late Oct to mid Nov) is now,
and the scorecard data is being collected from Phase 1 regardless.
- Plain-English heuristic, documented in `docs/stubble_heuristic.md`:
  1. **Fire load:** VIIRS hotspots in Punjab + Haryana over the last 24/48 h, weighted by FRP
     (counts filtered to the two states; the bounding box also covers Delhi and parts of
     Rajasthan and Himachal).
  2. **Transport:** share of forecast hours in the next 24–48 h with winds over the fire belt
     *from* roughly 270–340° (WNW–NNW, blowing toward Delhi) at a speed that carries smoke without
     scattering it.
  3. **Trapping:** low boundary layer × low wind in Delhi (the ventilation index) on the arrival day.
  4. Combine into **none / watch / likely**, always with the numbers that drove the result.
- Storage designed for an ML model later: a `features` table with an `as_of` timestamp (no
  look-ahead leakage), labels drawn from bulletin AQI, and predictions stored as forecasts from
  source `saans-stubble-v1`, so the heuristic is scored by the same scorecard.
- **Backtest on last season** using the 2025 bulletins, the FIRMS archive and the Open-Meteo
  historical weather/previous runs. This is the portfolio centrepiece: "here is how often the
  heuristic would have warned correctly".

**Done when:** the brief shows the warning with its reasons, and the backtest report for
Oct–Nov 2025 is in `docs/` (hit rate, false alarms, lead time).

## Phase 4: Forecast scorecard
- Parse every stored forecast into one `forecasts` table: source, issued_at, valid_for, lead time,
  location or city, value and/or category.
- Ground truth: CPCB bulletin for city-level daily values; nearest-station hourly NAQI for
  point forecasts.
- Metrics per source × lead time (day 0, +1, +2): **MAE** and **category hit rate**, plus bias,
  because "always forecasts too low" is the most likely failure.
- Sources: Open-Meteo (CAMS), IITM AQEWS (categories only), WAQI forecast (converted), and
  `saans-stubble-v1`.
- Scorecard section in the brief, plus a standalone `out/scorecard.html`.

**Done when:** the scorecard covers every day since Phase 1 started, with metrics recomputed
from raw data by one command.

## Phase 5: Our own forecast + going online (later)
- Bias-corrected forecast (e.g. CAMS + recent observed bias + stubble features) entered into the
  scorecard as `saans-v1`. It has to beat the others there before the brief relies on it.
- Move to a hosted site: a scheduled job (e.g. cron on a small VM or GitHub Actions), object storage
  for raw data, Postgres or kept SQLite, and a static brief/scorecard site. Check source terms first:
  Open-Meteo's free tier is non-commercial, and WAQI forbids redistributing cached data.
