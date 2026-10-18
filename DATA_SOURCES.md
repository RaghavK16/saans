# Data sources

Checked against each source's live docs **and** with a test request on **2026-10-18**.
Every endpoint below was either called successfully or is quoted from the provider's
own documentation. Nothing is guessed. Re-check this file whenever a collector breaks.

Status legend: ✅ called successfully · 🔑 needs a key (endpoint confirmed, waiting on your key) · ⚠️ works but unreliable

| Source | Role in Saans | Key? | Status | Backfill if we miss a day? |
|---|---|---|---|---|
| Open-Meteo Air Quality | Hourly pollutant forecast at any point (home, office, route) | No | ✅ | Forecasts: **no**. Past hours: yes, as analysis (up to 92 days) |
| Open-Meteo Weather | Wind, boundary-layer height (Delhi + Punjab/Haryana) | No | ✅ | Forecast history: yes (Previous Runs API) |
| CPCB via data.gov.in | Observed station readings, Delhi + Noida (latest snapshot) | Yes | ✅ with the public sample key | **No**: latest snapshot only |
| CPCB daily AQI bulletin (PDF) | Official city-level daily AQI: the scorecard's ground truth | No | ✅ | **Yes**: past bulletins are fetchable by date (tested back to 2025-11-01) |
| NASA FIRMS | Fire hotspots, Punjab + Haryana | Optional (MAP_KEY) | ✅ public files · 🔑 area API | Without a key: last 7 days. With a key: by date |
| OpenAQ v3 | Observed hourly concentrations with history | Yes | 🔑 | Yes, likely (to verify once we have a key) |
| WAQI / aqicn | Second observed feed + 3–8 day forecast | Yes (token) | 🔑 | **No** |
| IITM AQEWS (ews.tropmet.res.in) | Official Delhi AQI category forecast | No | ⚠️ unreachable from your network | **No** |

---

## 1. Open-Meteo: Air Quality API

- **Gives:** hourly `pm10`, `pm2_5`, `carbon_monoxide`, `nitrogen_dioxide`, `sulphur_dioxide`,
  `ozone` (all µg/m³), plus `dust`, `aerosol_optical_depth`, `uv_index`, and `us_aqi`/`european_aqi`.
  We ignore the last two because we compute CPCB NAQI ourselves. `ammonia` is **Europe-only**:
  it came back `null` for Delhi.
- **Endpoint:** `GET https://air-quality-api.open-meteo.com/v1/air-quality`
  - e.g. `?latitude=28.716&longitude=77.191&hourly=pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone&timezone=Asia/Kolkata&forecast_days=5&past_days=1`
  - `forecast_days` max 7 (default 5). `past_days` max 92.
- **Auth:** none for non-commercial use.
- **Rate limits (free tier):** 600/min, 5,000/hour, 10,000/day, 300,000/month. Non-commercial only.
  Data is CC BY 4.0, so we must credit Open-Meteo (and CAMS) wherever the data is shown.
- **Update frequency:** the CAMS global model runs every 12 h with a 5-day horizon.
- **Model / resolution for India:** CAMS Global. The docs give its native resolution as 0.4° (~45 km),
  3-hourly. In practice the API snapped Model Town to grid point (28.70, 77.20) and Noida to (28.60, 77.40),
  so the points it returns are finer than the model's real resolution.
- **Gaps:**
  - **Coarse.** Home and office get different numbers, but both come from a ~45 km model, so their
    difference is mostly interpolation, not a real local signal.
  - **Can't backfill forecasts.** Variables like `pm2_5_previous_day1` exist but returned `null` for
    every hour in Delhi. If we don't save a forecast on the day it's published, we lose it.
    This is the main argument for running Saans every day.
  - Global models are known to struggle with Delhi's winter episodes. The scorecard will measure
    how badly before we rely on it.

## 2. Open-Meteo: Weather Forecast API (wind for the stubble warning)

- **Gives:** hourly `wind_speed_10m` (km/h), `wind_direction_10m` (°), `boundary_layer_height` (m),
  and more. Tested for Ludhiana (30.9, 75.8): 288–306° winds (from the WNW, i.e. toward Delhi),
  boundary layer 35–65 m overnight.
- **Endpoint:** `GET https://api.open-meteo.com/v1/forecast?latitude=…&longitude=…&hourly=wind_speed_10m,wind_direction_10m,boundary_layer_height&timezone=Asia/Kolkata`
- **Previous runs:** `GET https://previous-runs-api.open-meteo.com/v1/forecast` with
  `<var>_previous_day1..N` **does** work for weather (tested). We can reconstruct "what the
  wind forecast said 1–2 days earlier" for backtests.
- **Auth / limits:** same as above. One shared free-tier budget.
- **Gaps:** model-level winds at 10 m. Smoke travels at roughly 500–1500 m. Good enough for a
  transparent heuristic; a trained model may want winds at higher pressure levels (also available).

## 3. CPCB observed stations via data.gov.in ("Real time Air Quality Index from various locations")

- **Gives:** one row per **station × pollutant**: `country, state, city, station, last_update,
  latitude, longitude, pollutant_id, min_value, max_value, avg_value`. Pollutants are
  `PM2.5, PM10, NO2, SO2, CO, OZONE, NH3`. A Delhi query returned 406 rows, about 58 stations.
  `last_update` is IST in `DD-MM-YYYY HH:MM:SS` format.
- **⚠️ The values look like sub-index values, not concentrations.** CO `avg_value` was 69–99. That is
  impossible in mg/m³ (the NAQI unit for CO), but fits an AQI sub-index. So this source gives us a
  station's AQI and its prominent pollutant, but **not** concentrations to recompute NAQI from.
  We'll confirm against the CPCB dashboard during Phase 1, and use OpenAQ for concentrations.
- **Endpoint:** `GET https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69?api-key=KEY&format=json&limit=1000&filters[city]=Delhi`
  - Other filters seen: `state`, `city`, `station`, `pollutant_id`. Paginate with `offset`.
  - Noida stations sit under `state=Uttar_Pradesh`, `city=Noida`. Confirm the exact spelling in Phase 1.
- **Auth:** an `api-key` query parameter. Without it the API returns
  `{"error": "Authorization field missing"}` with HTTP 400. The resource page embeds a public sample key
  that is capped at **10 records per call**. We used it once to verify the endpoint. Saans should use
  **your own key**.
- **Rate limits:** not published. Keep it to a handful of paginated calls per run.
- **Update frequency:** hourly (`updated_date` was 2026-10-17T19:04Z when we tested).
- **Gaps:** **latest snapshot only, no history.** A day we don't run is a day of observations
  lost from this source. (OpenAQ is the backfill plan.)

**How to get the key**
1. Go to https://www.data.gov.in and sign up / log in. The login flow has changed over the
   years, so follow whatever the site currently shows.
2. Open your account dashboard (it has been under *My Account*). Generate or copy your **API key**.
3. Put it in `.env` as `DATAGOVIN_API_KEY=…`.

## 4. CPCB daily AQI bulletin (PDF): official ground truth

- **Gives:** official city AQI at **4 PM IST**, defined as the average of the past 24 h. Each city row has:
  category, AQI value, prominent pollutant(s), and stations reporting / total stations.
  Example from 2026-10-17: `Delhi Moderate 159 PM2.5 55/59`, `Noida Poor 203 PM2.5, O3 4/4`.
- **Where:** linked from `https://cpcb.gov.in/AQI_Bulletin.php`, which lists about the last 10 days.
- **URL pattern (observed, not documented):**
  `https://cpcb.gov.in/displaypdf.php?id=<base64("Downloads/AQI_Bulletin_YYYYMMDD.pdf")>`
  - e.g. `id=RG93bmxvYWRzL0FRSV9CdWxsZXRpbl8yMDI2MTAxNy5wZGY=` →
    `Downloads/AQI_Bulletin_20261017.pdf`
  - Dates not on the listing page also work. 2026-09-01 and 2025-11-01 both came back as valid PDFs.
    That gives us **a full year of daily Delhi/Noida ground truth**, including last stubble season.
- **Auth / limits:** none published. We'll be polite: one request per date and a cache, never re-fetching.
- **Update frequency:** daily, published after 4 PM IST.
- **Gaps:**
  - It's a PDF, so we have to parse it. Text extraction works with `pypdf`, but the **layout varies
    by date**: the 2025-11-01 PDF didn't match the parser that handled 2026. We need
    fixture PDFs for each layout variant.
  - The URL scheme is undocumented and could change.
  - City-level and daily only. No hourly or per-station numbers.

## 5. NASA FIRMS: active fire hotspots

- **Gives:** satellite fire detections (lat, lon, brightness, FRP = fire radiative power,
  confidence, acquisition date/time, satellite). CSV format.
- **Endpoint (area API):**
  - Latest: `GET https://firms.modaps.eosdis.nasa.gov/api/area/csv/[MAP_KEY]/[SOURCE]/[west,south,east,north]/[DAY_RANGE]`
  - By date: `…/[DAY_RANGE]/[YYYY-MM-DD]`. Returns `[DATE]` through `[DATE + DAY_RANGE − 1]`.
  - `DAY_RANGE` is **1–5** (not 10, as some older tutorials say).
  - `SOURCE` options: `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`, `VIIRS_NOAA21_NRT`, `MODIS_NRT`;
    archive versions `*_SP`. We'll use the three VIIRS NRT products: 375 m resolution, several passes a day.
  - Data availability by date: `GET https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv/[MAP_KEY]/all`
  - Bounding box for Punjab + Haryana (approximate, set in `config.yaml`): `73.8,27.6,77.6,32.6`.
- **Auth:** `MAP_KEY` in the URL path. Calling without a valid key returns `Invalid MAP_KEY.` (HTTP 401).
- **Rate limits:** 5,000 transactions per 10 minutes. Multi-day requests count as several transactions.
- **Update frequency:** NRT data typically arrives within about 3 h of a satellite pass.
- **Gaps:**
  - Satellites see fires at fixed overpass times (VIIRS roughly 13:30 local), and smoke or cloud
    hides some fires. A hotspot count is a proxy for how much is burning, not a measure of emissions.
  - The FIRMS docs say real-time data is replaced once the NRT version is processed.

- **No-key alternative (found 2026-10-18, tested):** NASA publishes regional CSVs covering the
  last 24 h, 48 h and 7 d, with the same columns as the area API:
  `https://firms.modaps.eosdis.nasa.gov/data/active_fire/{folder}/csv/{prefix}_VIIRS_C2_South_Asia_{24h|48h|7d}.csv`
  with `suomi-npp-viirs-c2`/`SUOMI`, `noaa-20-viirs-c2`/`J1`, `noaa-21-viirs-c2`/`J2`.
  Each file is 0.1–0.7 MB and covers all of South Asia, so we filter it to the bbox ourselves. On
  2026-10-18 the NOAA-20 24 h file had 264 detections inside the Punjab/Haryana bbox.
  Saans uses these when there's no key (D-013).
- **Verified CSV header (VIIRS):** `latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,version,bright_ti5,frp,daynight`.
  `acq_time` is `HHMM` UTC. `confidence` is `low | nominal | high`. `satellite` is `N | N20 | N21`.

**How to get the key** (optional: adds exact date ranges and history beyond 7 days)
1. Go to https://firms.modaps.eosdis.nasa.gov/api/map_key/
2. Click **Get MAP Key** and enter your email. The key arrives by email.
3. Put it in `.env` as `FIRMS_MAP_KEY=…`. You can check your remaining transactions with
   the **Check status** button on the same page.

## 6. OpenAQ v3: observed concentrations with history

- **Gives:** locations, sensors and measurements, aggregated hourly or daily. OpenAQ collects
  readings from government monitors. **Whether it covers CPCB/DPCC stations in Delhi today is
  unverified**: the docs need a key, and we'll confirm coverage on the first call.
- **Endpoints:** base `https://api.openaq.org/v3/`
  - Locations near a point: `GET /v3/locations?coordinates=28.716,77.191&radius=10000`.
    Coordinates are given as **lat,lon**, and the radius is capped at **25,000 m**.
    Alternatively `bbox=minLon,minLat,maxLon,maxLat`. Don't combine the two (HTTP 422).
  - Sensor data: the `/v3/sensors/{id}/…` measurement and hourly endpoints. We'll pin the exact
    paths from the API reference when we build this collector, not before.
- **Auth:** `X-API-Key` header. Without it the API returns HTTP 401 with
  `Unauthorized. A valid API key must be provided in the X-API-Key header.`
- **Rate limits:** 60/min and 2,000/hour per key. Response headers `x-ratelimit-*` report usage.
  HTTP 429 means we're over the limit; repeated overuse can get the key banned.
- **Gaps:** network coverage and latency in India unknown until tested. Bulk archive also on AWS S3.

**How to get the key**
1. Register at https://explore.openaq.org/register
2. Copy the key from https://explore.openaq.org/account
3. Put it in `.env` as `OPENAQ_API_KEY=…`.

## 7. WAQI / aqicn.org

- **Gives:** station feeds with current AQI and per-pollutant values, plus a **3–8 day forecast**
  (per their docs).
- **Endpoints:** `https://api.waqi.info/feed/<city>/?token=…`. The docs also describe geo-location
  queries (lat/lng). The full reference at `aqicn.org/json-api/doc/` renders with JavaScript and
  couldn't be read here. We'll confirm the exact geo-feed path and forecast fields with a real token.
  **Note:** the `demo` token returned Shanghai even when we asked for Delhi coordinates, so it can't
  be used for verification.
- **Auth:** a `token` query parameter.
- **Rate limits:** "default quota is 1,000 requests per second".
- **Terms (important for a public repo/site):** the data can't be sold or redistributed **as cached
  or archived data**, and attribution to WAQI and the originating agency is mandatory. Non-profits
  must email them before public use. ⇒ We can store WAQI responses privately for the scorecard, but
  **never commit or publish the raw archive**.
- **Scale:** WAQI uses a US-EPA-style AQI (0–500, US breakpoints). That's **not NAQI**.
  We'll convert from their pollutant values, or score their forecast only on the pollutants they forecast.

**How to get the token**
1. Go to https://aqicn.org/data-platform/token/ and enter your email and name.
2. Click the confirmation link they email you. The token is shown or sent after that.
3. Put it in `.env` as `WAQI_TOKEN=…`.

## 8. IITM Air Quality Early Warning System (ews.tropmet.res.in)

- **Gives (from the page content):** the official Delhi bulletin. It has **AQI category** forecasts for
  today plus 3 days (e.g. the 17.10.2026 bulletin: Moderate 17–18 Oct, Poor 19–20 Oct), a 6-day outlook,
  forecast weather (temperature, wind, mixing depth, ventilation index), PM2.5 forecast map images,
  and pages for a 10-day forecast (`10_days_forecast.php`) and fire counts (`ob_fire_count.php`).
- **Endpoint:** **no API, data download or archive is published.** Getting this data means scraping HTML.
- **Reachability:** from your Mac, the TLS connection succeeds but the server sends nothing (timed out
  after 90 s, twice). A cloud fetcher got the homepage once, then got `ECONNREFUSED` on the 10-day page.
  The site is flaky.
- **Gaps:** mostly categories, not numbers (fine: the scorecard checks the category).
  No archive, so a missed day is lost. We'll treat it as **best effort**: a long timeout, never
  allowed to fail the run.
- Related: IMD publishes an all-India city bulletin as a PDF
  (`https://nwp.imd.gov.in/airqualityfc_bulletin_mausam.php` → `./silam/aqbulletin.pdf`).
  Not yet evaluated. Kept here as a fallback candidate.

---

## What you need to do

| Key | Needed for | `.env` variable |
|---|---|---|
| data.gov.in API key | Phase 1 | `DATAGOVIN_API_KEY` |
| NASA FIRMS MAP_KEY (optional; works without it, D-013) | Phase 1 | `FIRMS_MAP_KEY` |
| OpenAQ API key | Phase 2 | `OPENAQ_API_KEY` |
| WAQI token | Phase 2 | `WAQI_TOKEN` |
| WhatsApp Cloud API token + phone number ID (delivery, not data; see DECISIONS.md D-011) | Phase 2 | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TO` |

The four data keys are free. WhatsApp costs a few rupees a month (D-011). Saans skips a source and warns if its key is missing. It never crashes.
