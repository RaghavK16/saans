"""Per-location hourly air outlook: the single input every recommendation rule works from.

Rules never touch the database; they take Outlooks. Tests build Outlooks synthetically.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from saans import naqi
from saans.config import Config, Point
from saans.naqi import AqiResult, Pollutant

HOUR = timedelta(hours=1)

COLUMNS = {
    "pm10_ugm3": Pollutant.PM10,
    "pm25_ugm3": Pollutant.PM25,
    "no2_ugm3": Pollutant.NO2,
    "so2_ugm3": Pollutant.SO2,
    "o3_ugm3": Pollutant.O3,
    "co_mgm3": Pollutant.CO,
}


@dataclass(frozen=True)
class HourAir:
    local_time: datetime  # start of the forecast hour, local tz; the row covers [t, t + 1 h)
    instant: AqiResult
    official: AqiResult

    @property
    def end(self) -> datetime:
        return self.local_time + HOUR


@dataclass
class Outlook:
    point: Point
    hours: list[HourAir] = field(default_factory=list)  # sorted by local_time
    grid: tuple[float, float] | None = None
    issued_at: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.hours)

    def on(self, day: date) -> list[HourAir]:
        return [h for h in self.hours if h.local_time.date() == day]

    def covering(self, t: datetime) -> HourAir | None:
        for h in self.hours:
            if h.local_time <= t < h.end:
                return h
        return None

    def overlapping(self, start: datetime, end: datetime) -> list[HourAir]:
        return [h for h in self.hours if h.local_time < end and h.end > start]

    def days(self) -> list[date]:
        return sorted({h.local_time.date() for h in self.hours if h.instant.valid})


def worst(hours: Iterable[HourAir]) -> HourAir | None:
    valid = [h for h in hours if h.instant.valid]
    return max(valid, key=lambda h: h.instant.value) if valid else None


def best(hours: Iterable[HourAir]) -> HourAir | None:
    valid = [h for h in hours if h.instant.valid]
    return min(valid, key=lambda h: h.instant.value) if valid else None


def _parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_outlook(conn: sqlite3.Connection, point: Point, tz: ZoneInfo) -> Outlook:
    """Latest stored forecast for `point`, with instant and official NAQI for every hour."""
    latest = conn.execute(
        "SELECT MAX(raw_id) FROM aq_forecast_hourly WHERE location_key = ?", (point.key,)
    ).fetchone()[0]
    if latest is None:
        return Outlook(point)
    rows = conn.execute(
        "SELECT * FROM aq_forecast_hourly WHERE raw_id = ? AND location_key = ? ORDER BY valid_at",
        (latest, point.key),
    ).fetchall()
    series = {
        _parse_utc(r["valid_at"]): {p: r[c] for c, p in COLUMNS.items() if r[c] is not None}
        for r in rows
    }
    hours = [
        HourAir(at.astimezone(tz), naqi.instant(series, at), naqi.official(series, at))
        for at in sorted(series)
    ]
    return Outlook(point, hours, (rows[0]["lat"], rows[0]["lon"]), rows[0]["issued_at"])


def load_outlooks(conn: sqlite3.Connection, config: Config) -> dict[str, Outlook]:
    tz = ZoneInfo(config.timezone)
    points = list(config.locations.values()) + config.route_points
    return {p.key: load_outlook(conn, p, tz) for p in points}
