"""Assemble today's brief from stored data. Phase 1: outlook + observations + data health.

Recommendations (workout, windows, commute) arrive in Phase 2; this module only gathers facts.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from saans import naqi
from saans.config import Config, Point
from saans.naqi import AqiResult, Pollutant

COLUMNS = {
    "pm10_ugm3": Pollutant.PM10,
    "pm25_ugm3": Pollutant.PM25,
    "no2_ugm3": Pollutant.NO2,
    "so2_ugm3": Pollutant.SO2,
    "o3_ugm3": Pollutant.O3,
    "co_mgm3": Pollutant.CO,
}
FIRST_HOUR, LAST_HOUR = 6, 23  # IST hours shown in the outlook
STALE_RUN_GAP = timedelta(hours=26)


@dataclass
class HourOutlook:
    local_time: datetime
    instant: AqiResult
    official: AqiResult


@dataclass
class LocationOutlook:
    point: Point
    grid: tuple[float, float] | None
    issued_at: str | None
    hours: list[HourOutlook] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.hours)

    def peak(self) -> HourOutlook | None:
        valid = [h for h in self.hours if h.instant.valid]
        return max(valid, key=lambda h: h.instant.value) if valid else None

    def slot(self, start: str, end: str) -> list[HourOutlook]:
        s, e = int(start[:2]), int(end[:2])
        return [h for h in self.hours if s <= h.local_time.hour < e]


@dataclass
class StationObservation:
    station: str
    distance_km: float
    observed_at_local: datetime
    aqi: int | None
    prominent: str | None


@dataclass
class SourceHealth:
    source: str
    status: str
    detail: str
    last_ok: str | None


@dataclass
class Brief:
    day: date
    generated_at_local: datetime
    locations: list[LocationOutlook]
    observations: dict[str, list[StationObservation]]
    fires_24h: dict[str, tuple[int, float]] | None
    health: list[SourceHealth]
    previous_run_gap: timedelta | None
    bulletins_stored: int
    same_grid_cell: bool
    routine: dict
    notes: list[str] = field(default_factory=list)


def _parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _series(conn: sqlite3.Connection, location_key: str) -> tuple[dict, str | None, tuple | None]:
    latest = conn.execute(
        "SELECT MAX(raw_id) FROM aq_forecast_hourly WHERE location_key = ?", (location_key,)
    ).fetchone()[0]
    if latest is None:
        return {}, None, None
    rows = conn.execute(
        "SELECT * FROM aq_forecast_hourly WHERE raw_id = ? AND location_key = ? ORDER BY valid_at",
        (latest, location_key),
    ).fetchall()
    series = {
        _parse_utc(r["valid_at"]): {p: r[c] for c, p in COLUMNS.items() if r[c] is not None}
        for r in rows
    }
    return series, rows[0]["issued_at"], (rows[0]["lat"], rows[0]["lon"])


def location_outlook(conn: sqlite3.Connection, point: Point, day: date, tz: ZoneInfo) -> LocationOutlook:
    """Hours of `day` (local) between FIRST_HOUR and LAST_HOUR, at the forecast's own timestamps.

    Open-Meteo hours are UTC-aligned, which is HH:30 in IST (+05:30). We show them as they are
    rather than interpolating to :00, so every number in the brief is one the provider published.
    """
    series, issued_at, grid = _series(conn, point.key)
    out = LocationOutlook(point, grid, issued_at)
    for at in sorted(series):
        local = at.astimezone(tz)
        if local.date() == day and FIRST_HOUR <= local.hour <= LAST_HOUR:
            out.hours.append(HourOutlook(local, naqi.instant(series, at), naqi.official(series, at)))
    return out


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_stations(conn: sqlite3.Connection, point: Point, tz: ZoneInfo, n: int = 2) -> list[StationObservation]:
    """Latest snapshot. Station AQI = max sub-index across pollutants (provisional, see §3)."""
    latest = conn.execute("SELECT MAX(raw_id) FROM station_readings WHERE city = ?",
                          (point.cpcb_city,)).fetchone()[0]
    if latest is None:
        return []
    rows = conn.execute(
        "SELECT * FROM station_readings WHERE city = ? AND raw_id IN "
        "(SELECT id FROM raw_responses WHERE run_id = (SELECT run_id FROM raw_responses WHERE id = ?))",
        (point.cpcb_city, latest),
    ).fetchall()
    stations: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        if r["lat"] is not None and r["lon"] is not None:
            stations.setdefault(r["station"], []).append(r)
    obs = []
    for name, readings in stations.items():
        valued = [r for r in readings if r["avg_value"] is not None]
        top = max(valued, key=lambda r: r["avg_value"]) if valued else None
        obs.append(StationObservation(
            station=name,
            distance_km=haversine_km(point.lat, point.lon, readings[0]["lat"], readings[0]["lon"]),
            observed_at_local=_parse_utc(max(r["observed_at"] for r in readings)).astimezone(tz),
            aqi=int(round(top["avg_value"])) if top else None,
            prominent=top["pollutant"] if top else None,
        ))
    return sorted(obs, key=lambda o: o.distance_km)[:n]


def fire_summary(conn: sqlite3.Connection, now: datetime) -> dict[str, tuple[int, float]] | None:
    """Detections in the last 24 h per satellite product (count, total FRP in MW).

    Reported per product because the satellites overlap: summing them would double count.
    How to combine them into one fire-load number is a Phase 3 decision.
    """
    if conn.execute("SELECT 1 FROM fire_hotspots LIMIT 1").fetchone() is None:
        return None
    since = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT product, COUNT(*), COALESCE(SUM(frp_mw), 0) FROM fire_hotspots "
        "WHERE acquired_at >= ? GROUP BY product ORDER BY product", (since,)).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def source_health(conn: sqlite3.Connection, run_id: int | None) -> list[SourceHealth]:
    from saans.runner import SOURCES

    out = []
    for s in SOURCES:
        row = conn.execute("SELECT status, detail FROM source_runs WHERE run_id = ? AND source = ?",
                           (run_id, s.name)).fetchone() if run_id else None
        last_ok = conn.execute("SELECT MAX(fetched_at) FROM raw_responses WHERE source = ? AND ok = 1",
                               (s.name,)).fetchone()[0]
        out.append(SourceHealth(s.name, row["status"] if row else "not run",
                                row["detail"] if row else "", last_ok))
    return out


def build_brief(conn: sqlite3.Connection, config: Config, now: datetime) -> Brief:
    tz = ZoneInfo(config.timezone)
    local_now = now.astimezone(tz)
    day = local_now.date()
    runs = conn.execute(
        "SELECT id, started_at FROM runs WHERE command IN ('run', 'collect') ORDER BY id DESC LIMIT 2"
    ).fetchall()
    run_id = runs[0]["id"] if runs else None
    gap = (_parse_utc(runs[0]["started_at"]) - _parse_utc(runs[1]["started_at"])) if len(runs) == 2 else None

    locations = [location_outlook(conn, config.locations[k], day, tz) for k in ("home", "office")]
    grids = {loc.grid for loc in locations if loc.grid}
    bulletins = conn.execute(
        "SELECT COUNT(DISTINCT request_key) FROM raw_responses WHERE source='cpcb_bulletin' AND ok=1"
    ).fetchone()[0]

    brief = Brief(
        day=day,
        generated_at_local=local_now,
        locations=locations,
        observations={k: nearest_stations(conn, config.locations[k], tz) for k in ("home", "office")},
        fires_24h=fire_summary(conn, now),
        health=source_health(conn, run_id),
        previous_run_gap=gap,
        bulletins_stored=bulletins,
        same_grid_cell=len(grids) == 1,
        routine=config.routine,
    )
    if gap and gap > STALE_RUN_GAP:
        missed = gap.days
        brief.notes.append(
            f"{missed} day(s) since the previous run: forecasts and station snapshots for that "
            "period can't be recovered (DECISIONS.md D-003)."
        )
    if not any(loc.available for loc in locations):
        brief.notes.append("No forecast stored yet: run `saans run` (Open-Meteo needs no key).")
    return brief
