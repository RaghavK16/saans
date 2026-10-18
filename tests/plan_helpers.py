"""Build synthetic Outlooks for scenario tests: one instant NAQI value per forecast hour."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from saans.config import Point
from saans.naqi import AqiResult, Pollutant, category
from saans.plan.outlook import HourAir, Outlook

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 10, 19)  # a Monday


def aqi(value: int | None, pollutant: Pollutant = Pollutant.PM25) -> AqiResult:
    if value is None:
        return AqiResult(None, None, (), {})
    return AqiResult(value, category(value), (pollutant,), {pollutant: value})


def outlook(key: str, values_by_hour: dict[int, int | None] | None = None, *, day: date = DAY,
            default: int | None = None, days: int = 1, start_minute: int = 30) -> Outlook:
    """Hours run HH:30 IST like real Open-Meteo data. values_by_hour overrides `default`."""
    hours = []
    for d in range(days):
        for hh in range(24):
            t = datetime(day.year, day.month, day.day, hh, start_minute, tzinfo=IST) + timedelta(days=d)
            v = (values_by_hour or {}).get(hh, default) if d == 0 else default
            hours.append(HourAir(t, aqi(v), aqi(v)))
    return Outlook(Point(key, key.title(), 28.7, 77.2), hours, (28.7, 77.2), "2026-10-19T00:30:00Z")


def at(hh: int, mm: int = 0, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=IST)


ROUTINE = {
    "workout_slots": ["08:00-09:00", "20:00-21:00"],
    "office_days_per_week": 3,
    "office_hours": "11:00-17:00",
    "depart_home_window": "09:00-10:30",
    "depart_office_window": "16:30-18:30",
    "commute_minutes": 75,
}
THRESHOLDS = {"outdoor_ok_max": 100, "outdoor_light_max": 150, "windows_open_max": 100,
              "recirculate_above": 100, "spike_alert_above": 200}
