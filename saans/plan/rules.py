"""Shared types and helpers for recommendation rules."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time

from saans.plan.outlook import HourAir


@dataclass
class Recommendation:
    topic: str            # workout | home_air | commute | office_days
    headline: str         # one line; becomes a line of the WhatsApp summary
    reasons: list[str] = field(default_factory=list)  # the numbers behind the headline
    ok: bool = True       # False when the data wasn't enough to decide


def parse_window(spec: str) -> tuple[time, time]:
    start, end = spec.split("-")
    return time.fromisoformat(start.strip()), time.fromisoformat(end.strip())


def window_on(day: date, spec: str, tz) -> tuple[datetime, datetime]:
    s, e = parse_window(spec)
    return datetime.combine(day, s, tz), datetime.combine(day, e, tz)


def fmt_window(start: datetime, end: datetime) -> str:
    return f"{start:%H:%M}–{end:%H:%M}"


def value_range(hours: Iterable[HourAir]) -> str:
    vals = [h.instant.value for h in hours if h.instant.valid]
    if not vals:
        return "no data"
    lo, hi = min(vals), max(vals)
    return f"{lo}" if lo == hi else f"{lo}–{hi}"


def describe(h: HourAir) -> str:
    """'166 Moderate, PM2.5'"""
    if not h.instant.valid:
        return "no data"
    return f"{h.instant.value} {h.instant.category}, {'/'.join(h.instant.prominent)}"
