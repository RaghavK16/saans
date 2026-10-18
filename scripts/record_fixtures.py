"""Record live responses into tests/fixtures/ (the ONLY place tests get data from).

Usage:  .venv/bin/python scripts/record_fixtures.py [source ...]

Keyless sources record as-is. Keyed sources are recorded only when the key is in .env,
and every secret is scrubbed from what gets written. Never record WAQI (terms, D-005).
"""

from __future__ import annotations

import base64
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from saans.config import load_config  # noqa: E402
from saans.raw import redact  # noqa: E402
from saans.sources import open_meteo  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def _save(rel: str, content: bytes, secrets: list[str]) -> None:
    for s in secrets:
        if s.encode() in content:
            content = content.replace(s.encode(), b"REDACTED")
    path = FIXTURES / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    print(f"wrote {path.relative_to(ROOT)} ({len(content):,} bytes)")


def main(selected: list[str]) -> None:
    cfg = load_config(ROOT / "config.yaml")
    secrets = cfg.secrets.all_values()
    client = httpx.Client(timeout=60, headers={"User-Agent": cfg.user_agent})

    def want(name: str) -> bool:
        return not selected or name in selected

    if want("open_meteo_aq"):
        src = open_meteo.OpenMeteoAirQuality()
        pts = list(cfg.locations.values()) + cfg.route_points
        r = client.get(open_meteo.AQ_URL, params={
            **open_meteo._coords(pts), "hourly": ",".join(src.VARIABLES),
            "forecast_days": 5, "past_days": 1})
        r.raise_for_status()
        _save("open_meteo_aq/forecast.json", r.content, secrets)

    if want("open_meteo_weather"):
        src = open_meteo.OpenMeteoWeather()
        pts = cfg.wind_points + list(cfg.locations.values())
        r = client.get(open_meteo.WEATHER_URL, params={
            **open_meteo._coords(pts), "hourly": ",".join(src.VARIABLES),
            "forecast_days": 3, "past_days": 1})
        r.raise_for_status()
        _save("open_meteo_weather/forecast.json", r.content, secrets)

    if want("cpcb_bulletin_missing"):
        missing = base64.b64encode(b"Downloads/AQI_Bulletin_20991231.pdf").decode()
        r = client.get("https://cpcb.gov.in/displaypdf.php", params={"id": missing})
        _save("cpcb_bulletin/missing_date.html", r.content, secrets)

    if want("datagovin") and cfg.secrets.get("DATAGOVIN_API_KEY"):
        r = client.get(
            "https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69",
            params={"api-key": cfg.secrets.get("DATAGOVIN_API_KEY"), "format": "json",
                    "limit": 60, "filters[city]": "Delhi"})
        r.raise_for_status()
        _save("datagovin/delhi_page.json", r.content, secrets)

    if want("firms") and cfg.secrets.get("FIRMS_MAP_KEY"):
        bbox = ",".join(str(x) for x in cfg.fire_bbox)
        url = (f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
               f"{cfg.secrets.get('FIRMS_MAP_KEY')}/VIIRS_NOAA20_NRT/{bbox}/1")
        r = client.get(url)
        r.raise_for_status()
        _save("firms/viirs_noaa20_live.csv", r.content, secrets)

    print("recorded at", datetime.now(timezone.utc).isoformat(timespec="seconds"),
          "| urls:", redact(", ".join(selected) or "all", secrets))


if __name__ == "__main__":
    main(sys.argv[1:])
