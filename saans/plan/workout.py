"""Workout: which of your slots, and outdoors or gym (DECISIONS.md D-010).

Each slot is judged by its *worst* forecast hour (conservative: you breathe hardest while
training). Verdicts use instant NAQI against config thresholds:
  <= outdoor_ok_max     -> outdoors
  <= outdoor_light_max  -> outdoors, but easy and shorter
  otherwise             -> gym
If every slot today has already ended, the advice is for tomorrow's slots.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from saans.plan.outlook import HourAir, Outlook, worst
from saans.plan.rules import Recommendation, describe, fmt_window, value_range, window_on

OUTDOORS, LIGHT, GYM = "outdoors", "outdoors, easy and short", "gym"


@dataclass
class SlotCall:
    start: datetime
    end: datetime
    hours: list[HourAir]
    peak: HourAir | None
    verdict: str | None  # None = no data
    past: bool

    @property
    def label(self) -> str:
        return fmt_window(self.start, self.end)


def verdict(value: int, thresholds: dict[str, float]) -> str:
    if value <= thresholds.get("outdoor_ok_max", 100):
        return OUTDOORS
    if value <= thresholds.get("outdoor_light_max", 150):
        return LIGHT
    return GYM


def evaluate_slots(home: Outlook, slots: list[str], day, now: datetime, thresholds) -> list[SlotCall]:
    calls = []
    for spec in slots:
        start, end = window_on(day, spec, now.tzinfo)
        hours = home.overlapping(start, end)
        peak = worst(hours)
        calls.append(SlotCall(
            start, end, hours, peak,
            verdict(peak.instant.value, thresholds) if peak else None,
            past=end <= now,
        ))
    return calls


def recommend_workout(home: Outlook, routine: dict, thresholds: dict, now: datetime) -> Recommendation:
    slots = routine.get("workout_slots", [])
    if not slots:
        return Recommendation("workout", "Workout: no slots configured", ok=False)

    day, title = now.date(), "Workout"
    calls = evaluate_slots(home, slots, day, now, thresholds)
    if all(c.past for c in calls):
        day, title = now.date() + timedelta(days=1), "Workout tomorrow"
        calls = evaluate_slots(home, slots, day, now, thresholds)

    reasons = []
    for c in calls:
        if c.past:
            reasons.append(f"{c.label}: already passed")
        elif c.peak is None:
            reasons.append(f"{c.label}: no forecast")
        else:
            reasons.append(f"{c.label}: instant NAQI {value_range(c.hours)}, worst hour "
                           f"{c.peak.local_time:%H:%M} ({describe(c.peak)}) → {c.verdict}")

    open_calls = [c for c in calls if not c.past and c.peak is not None]
    if not open_calls:
        return Recommendation("workout", f"{title}: no forecast for your slots; "
                              "check the AQI before heading out", reasons, ok=False)

    best = min(open_calls, key=lambda c: (c.peak.instant.value, c.start))
    worst_val = best.peak.instant.value
    if best.verdict == OUTDOORS:
        headline = f"{title}: outdoors {best.label} (NAQI up to {worst_val})"
    elif best.verdict == LIGHT:
        headline = f"{title}: outdoors but easy and short, {best.label} (NAQI up to {worst_val})"
    else:
        limit = thresholds.get("outdoor_light_max", 150)
        where = f"least bad {best.label}" if len(open_calls) > 1 else best.label
        headline = (f"{title}: gym; outdoor NAQI reaches {worst_val} ({where}), "
                    f"above your {limit:.0f} limit for training outside")
    return Recommendation("workout", headline, reasons)
