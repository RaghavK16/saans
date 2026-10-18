-- Phase 1 schema. Three layers (DECISIONS.md D-004):
--   1. bookkeeping: runs, source_runs
--   2. raw index:   raw_responses (bodies live gzipped under data/raw/)
--   3. parsed:      rebuildable from raw via `saans reparse`
-- All timestamps are UTC ISO-8601 strings ("2026-10-18T05:30:00Z").

CREATE TABLE runs (
    id          INTEGER PRIMARY KEY,
    command     TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT                       -- ok | partial | failed
);

CREATE TABLE source_runs (
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    source      TEXT NOT NULL,
    status      TEXT NOT NULL,             -- ok | skipped | failed
    detail      TEXT,
    raw_count   INTEGER NOT NULL DEFAULT 0,
    row_count   INTEGER NOT NULL DEFAULT 0,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    PRIMARY KEY (run_id, source)
);

CREATE TABLE raw_responses (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER REFERENCES runs(id),
    source       TEXT NOT NULL,
    request_key  TEXT,                     -- source-specific identity, e.g. a bulletin date
    url          TEXT NOT NULL,            -- secrets redacted
    params_json  TEXT NOT NULL DEFAULT '{}', -- context the parser needs (e.g. location keys)
    fetched_at   TEXT NOT NULL,
    status_code  INTEGER,
    content_type TEXT,
    sha256       TEXT,
    bytes        INTEGER,
    path         TEXT,                     -- relative to data/raw/
    ok           INTEGER NOT NULL,         -- 1 = usable payload
    error        TEXT
);
CREATE INDEX ix_raw_source_key  ON raw_responses(source, request_key);
CREATE INDEX ix_raw_source_time ON raw_responses(source, fetched_at);

-- Point forecasts of pollutant concentrations (Open-Meteo / CAMS, later others).
-- issued_at = when we fetched it (the provider does not expose its model run time).
CREATE TABLE aq_forecast_hourly (
    raw_id       INTEGER NOT NULL REFERENCES raw_responses(id),
    source       TEXT NOT NULL,
    location_key TEXT NOT NULL,
    lat          REAL NOT NULL,            -- grid point actually returned
    lon          REAL NOT NULL,
    issued_at    TEXT NOT NULL,
    valid_at     TEXT NOT NULL,
    pm10_ugm3    REAL,
    pm25_ugm3    REAL,
    no2_ugm3     REAL,
    so2_ugm3     REAL,
    o3_ugm3      REAL,
    co_mgm3      REAL,                     -- NAQI uses mg/m3 for CO
    PRIMARY KEY (raw_id, location_key, valid_at)
);
CREATE INDEX ix_aqf_lookup ON aq_forecast_hourly(location_key, valid_at, issued_at);

CREATE TABLE weather_forecast_hourly (
    raw_id          INTEGER NOT NULL REFERENCES raw_responses(id),
    source          TEXT NOT NULL,
    location_key    TEXT NOT NULL,
    lat             REAL NOT NULL,
    lon             REAL NOT NULL,
    issued_at       TEXT NOT NULL,
    valid_at        TEXT NOT NULL,
    wind_speed_kmh  REAL,
    wind_dir_deg    REAL,
    blh_m           REAL,                  -- boundary layer height
    temperature_c   REAL,
    PRIMARY KEY (raw_id, location_key, valid_at)
);
CREATE INDEX ix_wxf_lookup ON weather_forecast_hourly(location_key, valid_at, issued_at);

-- CPCB station snapshot via data.gov.in. One row per station x pollutant.
-- min/max/avg appear to be sub-index values, not concentrations (DATA_SOURCES.md §3).
CREATE TABLE station_readings (
    raw_id       INTEGER NOT NULL REFERENCES raw_responses(id),
    source       TEXT NOT NULL,
    station      TEXT NOT NULL,
    city         TEXT,
    state        TEXT,
    lat          REAL,
    lon          REAL,
    pollutant    TEXT NOT NULL,            -- PM2.5 | PM10 | NO2 | SO2 | CO | OZONE | NH3
    observed_at  TEXT NOT NULL,            -- last_update converted to UTC
    min_value    REAL,
    max_value    REAL,
    avg_value    REAL,
    PRIMARY KEY (raw_id, station, pollutant)
);
CREATE INDEX ix_station_time ON station_readings(station, observed_at);

-- NASA FIRMS hotspots. Overlapping catch-up windows return the same detection twice,
-- so the natural key de-duplicates across raw responses.
CREATE TABLE fire_hotspots (
    product      TEXT NOT NULL,            -- e.g. VIIRS_NOAA20_NRT
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    acquired_at  TEXT NOT NULL,            -- UTC, from acq_date + acq_time
    raw_id       INTEGER NOT NULL REFERENCES raw_responses(id),  -- first response seen in
    satellite    TEXT,
    confidence   TEXT,
    frp_mw       REAL,                     -- fire radiative power
    bright_ti4_k REAL,
    daynight     TEXT,
    PRIMARY KEY (product, lat, lon, acquired_at)
);
CREATE INDEX ix_fire_time ON fire_hotspots(acquired_at);
