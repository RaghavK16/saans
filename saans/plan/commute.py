"""Commute: least-bad departure in each window, and when to switch the car to recirculation.

Model: the drive takes `commute_minutes`; the car passes the route points (home → route
points → office, reversed in the evening) at evenly spaced times. A departure's score is the
mean instant NAQI over those samples (exposure); the worst sample sets the recirculation call.
Candidate departures are every 30 minutes inside the configured window.
Weekdays only: office days are Mon–Fri (D-010).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from saans.plan.outlook import HourAir, Outlook
from saans.plan.rules import Recommendation, window_on

STEP = timedelta(minutes=30)
CO2_TIP_AFTER_MIN = 30


@dataclass
class Sample:
    place: str
    passes_at: datetime
    hour: HourAir | None

    @property
    def value(self) -> int | None:
        return self.hour.instant.value if self.hour and self.hour.instant.valid else None


@dataclass
class Departure:
    leave: datetime
    samples: list[Sample]

    @property
    def values(self) -> list[int]:
        return [s.value for s in self.samples if s.value is not None]

    @property
    def score(self) -> float | None:
        v = self.values
        return sum(v) / len(v) if len(v) * 2 >= len(self.samples) else None  # need half the route

    @property
    def peak(self) -> int | None:
        return max(self.values) if self.values else None


def evaluate(route: list[Outlook], leave: datetime, minutes: int) -> Departure:
    n = len(route)
    samples = []
    for i, o in enumerate(route):
        t = leave + timedelta(minutes=minutes * i / max(n - 1, 1))
        samples.append(Sample(o.point.name, t, o.covering(t)))
    return Departure(leave, samples)


def candidates(day: date, spec: str, tz) -> list[datetime]:
    start, end = window_on(day, spec, tz)
    out, t = [], start
    while t <= end:
        out.append(t)
        t += STEP
    return out


def best_departure(route: list[Outlook], day: date, spec: str, minutes: int, tz,
                   not_before: datetime | None = None) -> tuple[Departure | None, list[Departure]]:
    deps = [evaluate(route, t, minutes) for t in candidates(day, spec, tz)
            if not_before is None or t >= not_before]
    scored = [d for d in deps if d.score is not None]
    if not scored:
        return None, deps
    return min(scored, key=lambda d: (round(d.score), d.leave)), deps


def recirculation(dep: Departure, threshold: float) -> str:
    bad = [s.value is not None and s.value > threshold for s in dep.samples]
    if all(bad):
        return "recirculate the whole way"
    if not any(bad):
        return "fresh-air mode is fine"
    first = bad.index(True)
    if all(bad[first:]):
        return f"recirculate from {dep.samples[first].place} onward"
    return "recirculate around " + ", ".join(s.place for s, b in zip(dep.samples, bad) if b)


def _leg(name: str, route: list[Outlook], day: date, spec: str, minutes: int, threshold: float,
         now: datetime) -> tuple[str | None, list[str]]:
    _, end = window_on(day, spec, now.tzinfo)
    if end < now:
        return None, [f"{name}: window {spec} has passed"]
    best, deps = best_departure(route, day, spec, minutes, now.tzinfo, not_before=now - STEP)
    if best is None:
        return None, [f"{name}: no forecast for {spec}"]
    recirc = recirculation(best, threshold)
    scored = [d for d in deps if d.score is not None]
    worst = max(scored, key=lambda d: d.score)
    lines = [f"{name}: leave {best.leave:%H:%M} (route NAQI ~{best.score:.0f}, peak {best.peak} "
             f"at {next(s.place for s in best.samples if s.value == best.peak)}); {recirc}"]
    if worst.score - best.score >= 15:
        lines.append(f"{name}: leaving {best.leave:%H:%M} instead of {worst.leave:%H:%M} cuts route "
                     f"NAQI from ~{worst.score:.0f} to ~{best.score:.0f}")
    lines.append(f"{name}: " + ", ".join(f"{d.leave:%H:%M} ~{d.score:.0f}" for d in scored))
    if recirc != "fresh-air mode is fine" and minutes > CO2_TIP_AFTER_MIN:
        lines.append(f"{name}: on recirculation for {minutes} min, let fresh air in for a minute "
                     "every 20–30 min (CO₂ builds up and makes you drowsy)")
    summary = f"leave {best.leave:%H:%M} (~{best.score:.0f}, {recirc})"
    return summary, lines


def recommend_commute(home_to_office: list[Outlook], routine: dict, thresholds: dict,
                      now: datetime) -> Recommendation:
    minutes = int(routine.get("commute_minutes", 75))
    threshold = thresholds.get("recirculate_above", 100)
    day, title = now.date(), "Commute"
    _, evening_end = window_on(day, routine["depart_office_window"], now.tzinfo)
    if now > evening_end:
        day, title = day + timedelta(days=1), "Commute tomorrow"
    if day.weekday() >= 5:
        return Recommendation("commute", f"{title}: none (weekend)")

    office_to_home = list(reversed(home_to_office))
    morning, m_lines = _leg("Morning", home_to_office, day, routine["depart_home_window"],
                            minutes, threshold, now)
    evening, e_lines = _leg("Return", office_to_home, day, routine["depart_office_window"],
                            minutes, threshold, now)
    parts = [p for p in (morning and f"{morning}", evening and f"return {evening}") if p]
    if not parts:
        return Recommendation("commute", f"{title}: no forecast for your departure windows",
                              m_lines + e_lines, ok=False)
    reasons = m_lines + e_lines
    grids = {o.grid for o in home_to_office if o.grid}
    if grids and len(grids) < len(home_to_office):
        reasons.append(f"The {len(home_to_office)} route points fall in {len(grids)} forecast grid "
                       "cells, so the route profile is coarse; CPCB stations along the route will "
                       "sharpen it.")
    return Recommendation("commute", f"{title} (if you go in): " + "; ".join(parts), reasons)
