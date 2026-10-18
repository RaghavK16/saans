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

## D-011 · Push channel: WhatsApp via Meta's official Cloud API
*2026-10-18 · Accepted · Owner: user · Build in Phase 2*

**Context.** After the HTML/Markdown brief, we need one push channel to the user's phone. I compared
Telegram, email and Google Calendar and recommended **Telegram** (least setup, easy to host).
The table is kept below as originally written. **The user chose WhatsApp**, the app they already
check every morning. A notification only helps if it lands where you already look, and that
outweighs setup cost. So I researched how to do WhatsApp properly (2026-10-18).

**WhatsApp options considered**

| Option | How | Verdict |
|---|---|---|
| **Meta WhatsApp Cloud API** (official) | Meta developer app + business portfolio. Messages go out from a business number. `POST https://graph.facebook.com/v23.0/<PHONE_NUMBER_ID>/messages` with a Bearer token | **Chosen** |
| CallMeBot | Free personal-use bot: a GET request with an apikey | Rejected: sign-ups currently closed ("the bot is currently full"), unofficial, no SLA, and a third party sees every message |
| Unofficial WhatsApp Web libraries (Baileys, whatsapp-web.js) | Automate your own logged-in account | Rejected: against WhatsApp's terms, and puts your personal number at risk of a ban |
| Twilio WhatsApp | Official provider (BSP) on top of Meta | Rejected for v1: same Meta rules and fees, plus Twilio's markup and another account |

**What the official API means for the product (from Meta's docs)**
- **Sender:** messages come from a business number, not from yourself. A number already active on
  WhatsApp *can't* be registered ("Numbers already in use with WhatsApp cannot be registered unless
  they are deleted first"). Start with the **test number Meta generates** during setup. Move to a
  dedicated number when hosting.
- **Templates:** a daily brief is a business-initiated message, so it must use a **pre-approved
  template** unless the user has messaged the bot in the last 24 h (the "customer service window").
  ⇒ Saans needs a **utility template** with a few variables. This is a useful product constraint:
  it forces the brief into about 5 one-line answers (workout · windows · commute · stubble · headline AQI).
  The full brief stays in the HTML file (and on the site link, once hosted).
- **Cost:** per-message pricing since 2025-07-01. Utility templates are charged only when delivered
  *outside* an open window, and are free inside one. Third-party sources put India's utility rate at
  about ₹0.115 per message (≈ ₹3.5/month for one daily brief). Not yet confirmed against Meta's INR rate card.
- **Token:** the dashboard's temporary token "expires quickly". Saans needs a **system-user
  token** (permissions `whatsapp_business_messaging`, `whatsapp_business_management`,
  `business_management`) stored in `.env`.
- **Later upgrade:** once hosted with a webhook, the user can reply "brief" to open a 24 h window, and
  replies become free-form and free. Out of scope until the project is online.

**Design.** Delivery is an adapter (`saans/delivery/whatsapp.py` behind a `Notifier` interface), so
Telegram, email or Calendar can be added without touching plan logic. Tests mock the Graph API
with recorded or synthetic responses. A failed send never fails the run, and the brief file is always written.

**What the user will need to do (Phase 2, steps verified then):** create a Meta developer account →
create an app with the WhatsApp product and a business portfolio → add their phone as a recipient of
the test number → create a system user and generate a token → submit the `saans_daily_brief` utility
template for approval. `.env`: `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TO`.

**Risks / revisit if.** Meta tightens use of test numbers, the template is rejected (Meta may reject a
template that's all variables, so the template needs fixed wording around them), or costs change.
Fallback order: email, then Telegram.

<details><summary>Original comparison (Telegram recommended)</summary>

| | Telegram bot | Email | Google Calendar events |
|---|---|---|---|
| Setup | Create a bot via @BotFather, get chat id (~5 min) | SMTP + Gmail app password (needs 2FA) | Google Cloud project + OAuth consent |
| Phone experience | Instant push, readable on the lock screen | Lands in an inbox; easy to ignore | Time blocks ("Run outside 20:00", "Leave 09:40") with reminders |
| Fits "what to do today" | Good | OK | Excellent for windows, poor for explanations |
| Fails when | Telegram unavailable | Spam filters | Event duplication/updates are fiddly |
| Moves online | Trivially (one HTTPS call) | Easy | Needs token refresh handled on the server |
| Cost | Free | Free | Free |

</details>

## D-012 · How Saans computes NAQI where the CPCB table leaves gaps
*2026-10-18 · Accepted*

**Context.** CPCB's 2014 NAQI table gives integer concentration ranges (e.g. PM2.5 0–30, 31–60),
an open-ended Severe band ("250+"), and the rules (at least 3 pollutants including PM2.5 or PM10,
at least 16 h of data, the highest sub-index wins). The breakpoints were cross-checked on 2026-10-18
against two independent reproductions of the CPCB table (ies.gov.in Arthapedia, and the CPCB 2014
table as cited by PMC). The official CPCB PDF host wasn't reachable.
**Gaps and our choices.**
- *Between bands* (e.g. PM2.5 = 30.6): round concentrations half-up to the table's precision
  (integers; 1 decimal for CO and Pb) before lookup. Rejected: a continuous interpolation that
  ignores the integer edges, which gives values up to ~2 points off CPCB near band edges.
- *Severe band upper limit:* extrapolate with the width of the Very Poor band (PM2.5: 251→380 maps
  to 401→500), then cap at 500. Rejected: the US-EPA-style 500 ceiling at arbitrary concentrations.
- *8 h coverage for CO/O₃:* require at least 6 of 8 hours (CPCB only states the 16-of-24 rule).
- *Rolling 8 h for CO/O₃:* the mean of the last 8 hours. CPCB's dashboard may instead use the maximum
  8 h mean over the day. **To verify** against the CPCB dashboard in Phase 4. It only affects the
  official mode.
**Why.** Agreeing with the bulletin matters more than mathematical neatness. Each assumption is
isolated in `saans/naqi.py` and pinned by a test.
**Revisit if.** The scorecard shows a systematic offset between our computed city NAQI and the
CPCB bulletin.
