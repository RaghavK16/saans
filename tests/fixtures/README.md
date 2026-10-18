# Test fixtures

Recorded from the live services (see `scripts/record_fixtures.py`) unless noted. Secrets are scrubbed.

| File | Origin |
|---|---|
| `open_meteo_aq/forecast.json`, `open_meteo_weather/forecast.json` | Live, 2026-10-18 |
| `cpcb_bulletin/missing_date.html` | Live: CPCB's response for a date with no bulletin |
| `datagovin/delhi_page.json`, `noida_page.json` | Live, 2026-10-18, fetched with data.gov.in's public sample key (10-record cap) |
| `firms/J1_VIIRS_C2_South_Asia_sample.csv` | Live public NOAA-20 24 h South Asia file, 2026-10-18, trimmed to 40 rows inside the Punjab/Haryana bbox + 5 outside |

Never commit WAQI responses (their terms forbid redistributing cached data; DECISIONS.md D-005).
