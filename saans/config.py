"""Load config.yaml (non-secret, committed) and .env (secrets, gitignored)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

SECRET_ENV_VARS = (
    "DATAGOVIN_API_KEY",
    "FIRMS_MAP_KEY",
    "OPENAQ_API_KEY",
    "WAQI_TOKEN",
    "WHATSAPP_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_TO",
)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Point:
    key: str
    name: str
    lat: float
    lon: float
    cpcb_city: str | None = None


@dataclass(frozen=True)
class Secrets:
    values: dict[str, str] = field(default_factory=dict)

    def get(self, name: str) -> str | None:
        value = self.values.get(name)
        return value or None

    def all_values(self) -> list[str]:
        """Every non-empty secret, for redacting URLs and logs."""
        return [v for v in self.values.values() if v]


@dataclass(frozen=True)
class Config:
    root: Path
    timezone: str
    data_dir: Path
    out_dir: Path
    http_timeout: float
    user_agent: str
    locations: dict[str, Point]
    route_name: str
    route_points: list[Point]
    wind_points: list[Point]
    fire_bbox: tuple[float, float, float, float]
    routine: dict[str, Any]
    thresholds: dict[str, float]
    sources: dict[str, dict[str, Any]]
    secrets: Secrets

    @property
    def db_path(self) -> Path:
        return self.data_dir / "saans.db"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    def source_settings(self, name: str) -> dict[str, Any]:
        return self.sources.get(name, {})


def _point(key: str, d: dict[str, Any]) -> Point:
    try:
        lat, lon = float(d["lat"]), float(d["lon"])
    except (KeyError, TypeError, ValueError) as e:
        raise ConfigError(f"point {key!r} needs numeric lat and lon") from e
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ConfigError(f"point {key!r} has out-of-range coordinates")
    return Point(key=key, name=d.get("name", key), lat=lat, lon=lon, cpcb_city=d.get("cpcb_city"))


def load_secrets(env_file: Path | None) -> Secrets:
    values: dict[str, str] = {}
    if env_file and env_file.exists():
        values.update({k: v for k, v in dotenv_values(env_file).items() if v})
    # Real environment variables win over .env (useful for CI / hosting later).
    for name in SECRET_ENV_VARS:
        if os.environ.get(name):
            values[name] = os.environ[name]
    return Secrets({k: v for k, v in values.items() if k in SECRET_ENV_VARS})


def load_config(path: Path | str | None = None, env_file: Path | str | None = None) -> Config:
    path = Path(path or os.environ.get("SAANS_CONFIG", "config.yaml")).resolve()
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    root = path.parent
    env_path = Path(env_file) if env_file else root / ".env"

    storage = raw.get("storage", {})
    http = raw.get("http", {})
    try:
        locations = {k: _point(k, v) for k, v in raw["locations"].items()}
    except KeyError as e:
        raise ConfigError("config needs a `locations` section") from e
    for required in ("home", "office"):
        if required not in locations:
            raise ConfigError(f"locations.{required} is required")

    route = raw.get("route", {})
    bbox = tuple(float(x) for x in raw.get("fire_region", {}).get("bbox", ()))
    if len(bbox) != 4 or not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
        raise ConfigError("fire_region.bbox must be [west, south, east, north]")

    return Config(
        root=root,
        timezone=raw.get("timezone", "Asia/Kolkata"),
        data_dir=root / storage.get("data_dir", "data"),
        out_dir=root / storage.get("out_dir", "out"),
        http_timeout=float(http.get("timeout_seconds", 30)),
        user_agent=http.get("user_agent", "Saans/0.1"),
        locations=locations,
        route_name=route.get("name", ""),
        route_points=[_point(p["key"], p) for p in route.get("points", [])],
        wind_points=[_point(p["key"], p) for p in raw.get("wind_points", [])],
        fire_bbox=bbox,  # type: ignore[arg-type]
        routine=raw.get("routine", {}),
        thresholds={k: float(v) for k, v in raw.get("thresholds", {}).items()},
        sources=raw.get("sources", {}),
        secrets=load_secrets(env_path),
    )
