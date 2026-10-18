"""Recommendation engine: pure rules over per-location Outlooks (no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from saans.config import Config
from saans.plan.commute import recommend_commute
from saans.plan.home_air import recommend_home_air
from saans.plan.office_days import recommend_office_days
from saans.plan.outlook import Outlook
from saans.plan.rules import Recommendation, value_range
from saans.plan.workout import recommend_workout


@dataclass
class Plan:
    air_headline: str
    recommendations: list[Recommendation]

    @property
    def summary_lines(self) -> list[str]:
        """The short version: one line per question. This is the future WhatsApp payload (D-011)."""
        return [self.air_headline] + [r.headline for r in self.recommendations]


def air_headline(home: Outlook, now: datetime) -> str:
    rest_of_day = [h for h in home.on(now.date()) if h.end > now and h.local_time.time() <= time(23, 0)]
    current = home.covering(now)
    if not rest_of_day:
        return "Air (home): no forecast for the rest of today"
    line = f"Air (home), rest of today: instant NAQI {value_range(rest_of_day)}"
    if current and current.official.valid:
        line += f"; 24 h NAQI now {current.official.value} ({current.official.category})"
    return line


def make_plan(outlooks: dict[str, Outlook], config: Config, now: datetime) -> Plan:
    home = outlooks["home"]
    route = [home] + [outlooks[p.key] for p in config.route_points] + [outlooks["office"]]
    return Plan(
        air_headline(home, now),
        [
            recommend_workout(home, config.routine, config.thresholds, now),
            recommend_home_air(home, config.thresholds, now),
            recommend_commute(route, config.routine, config.thresholds, now),
            recommend_office_days(route, config.routine, now),
        ],
    )
