"""Open-Meteo: air-quality forecast (CAMS) and weather forecast. No key. DATA_SOURCES.md §1-2.

One request per collect covers every point (the API accepts comma-separated coordinates and
returns a list). Times are requested in GMT so they can be stored as UTC unchanged.
"""

from __future__ import annotations

import json
from typing import Any

from saans.config import Point
from saans.raw import RawRecord
from saans.sources.base import Row, RunContext, Source, json_ok

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


def _coords(points: list[Point]) -> dict[str, str]:
    return {
        "latitude": ",".join(f"{p.lat:.2f}" for p in points),
        "longitude": ",".join(f"{p.lon:.2f}" for p in points),
    }


def _as_list(payload: Any) -> list[dict[str, Any]]:
    return payload if isinstance(payload, list) else [payload]


def _utc(t: str) -> str:
    # GMT iso8601 without seconds, e.g. "2026-10-18T05:00" -> "2026-10-18T05:00:00Z"
    return f"{t}:00Z" if len(t) == 16 else t


def _hourly_rows(raw: RawRecord, body: bytes, mapping: dict[str, tuple[str, float]]) -> list[Row]:
    keys: list[str] = raw.params["location_keys"]
    blocks = _as_list(json.loads(body))
    if len(blocks) != len(keys):
        raise ValueError(f"expected {len(keys)} locations, got {len(blocks)}")
    rows: list[Row] = []
    for key, block in zip(keys, blocks):
        hourly = block["hourly"]
        for i, t in enumerate(hourly["time"]):
            row: Row = {
                "raw_id": raw.id,
                "source": "open-meteo",
                "location_key": key,
                "lat": block["latitude"],
                "lon": block["longitude"],
                "issued_at": raw.fetched_at,
                "valid_at": _utc(t),
            }
            for api_name, (col, scale) in mapping.items():
                v = hourly.get(api_name, [None] * len(hourly["time"]))[i]
                row[col] = None if v is None else v * scale
            rows.append(row)
    return rows


class OpenMeteoAirQuality(Source):
    name = "open_meteo_aq"
    table = "aq_forecast_hourly"

    # API variable -> (column, unit scale). CO arrives in ug/m3; NAQI wants mg/m3.
    VARIABLES = {
        "pm10": ("pm10_ugm3", 1.0),
        "pm2_5": ("pm25_ugm3", 1.0),
        "nitrogen_dioxide": ("no2_ugm3", 1.0),
        "sulphur_dioxide": ("so2_ugm3", 1.0),
        "ozone": ("o3_ugm3", 1.0),
        "carbon_monoxide": ("co_mgm3", 0.001),
    }

    def points(self, ctx: RunContext) -> list[Point]:
        return list(ctx.config.locations.values()) + ctx.config.route_points

    def collect(self, ctx: RunContext) -> list[RawRecord]:
        settings = ctx.config.source_settings(self.name)
        points = self.points(ctx)
        query = {
            **_coords(points),
            "hourly": ",".join(self.VARIABLES),
            "forecast_days": settings.get("forecast_days", 5),
            "past_days": settings.get("past_days", 1),
        }
        rec = ctx.fetcher.get(
            self.name, AQ_URL, query=query, run_id=ctx.run_id,
            params={"location_keys": [p.key for p in points]}, validate=json_ok,
        )
        return [rec]

    def parse(self, raw: RawRecord, body: bytes) -> list[Row]:
        return _hourly_rows(raw, body, self.VARIABLES)


class OpenMeteoWeather(Source):
    name = "open_meteo_weather"
    table = "weather_forecast_hourly"

    VARIABLES = {
        "wind_speed_10m": ("wind_speed_kmh", 1.0),
        "wind_direction_10m": ("wind_dir_deg", 1.0),
        "wind_speed_850hPa": ("wind_speed_850_kmh", 1.0),
        "wind_direction_850hPa": ("wind_dir_850_deg", 1.0),
        "boundary_layer_height": ("blh_m", 1.0),
        "temperature_2m": ("temperature_c", 1.0),
    }

    def points(self, ctx: RunContext) -> list[Point]:
        return ctx.config.wind_points + list(ctx.config.locations.values())

    def collect(self, ctx: RunContext) -> list[RawRecord]:
        settings = ctx.config.source_settings(self.name)
        points = self.points(ctx)
        query = {
            **_coords(points),
            "hourly": ",".join(self.VARIABLES),
            "forecast_days": settings.get("forecast_days", 3),
            "past_days": 1,
        }
        rec = ctx.fetcher.get(
            self.name, WEATHER_URL, query=query, run_id=ctx.run_id,
            params={"location_keys": [p.key for p in points]}, validate=json_ok,
        )
        return [rec]

    def parse(self, raw: RawRecord, body: bytes) -> list[Row]:
        return _hourly_rows(raw, body, self.VARIABLES)
