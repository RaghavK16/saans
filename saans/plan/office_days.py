"""Best office days: rank the week's remaining weekdays by forecast commute exposure.

You go in any `office_days_per_week` days (D-010). A day's score is the mean of its best
morning and best return departure scores (commute.py). The forecast reaches ~5 days ahead
(CAMS), so later days show as "no forecast yet" rather than being guessed.
Saans doesn't know which days you've already gone in; it ranks what's left of the week.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from saans.plan.commute import best_departure
from saans.plan.outlook import Outlook
from saans.plan.rules import Recommendation, window_on


@dataclass
class DayScore:
    day: date
    score: float | None
    morning: float | None
    evening: float | None

    @property
    def label(self) -> str:
        return f"{self.day:%a}"


def target_days(now: datetime, routine: dict) -> tuple[list[date], str]:
    """Remaining weekdays to plan (today counts until its morning window closes)."""
    today = now.date()
    _, morning_end = window_on(today, routine["depart_home_window"], now.tzinfo)
    start = today if now <= morning_end else today + timedelta(days=1)
    if start.weekday() >= 5:  # weekend: plan Monday to Friday
        start += timedelta(days=7 - start.weekday())
    friday = start + timedelta(days=4 - start.weekday())
    which = "this week" if start.isocalendar()[:2] == today.isocalendar()[:2] else "next week"
    return [start + timedelta(days=i) for i in range((friday - start).days + 1)], which


def score_day(route: list[Outlook], day: date, routine: dict) -> DayScore:
    minutes = int(routine.get("commute_minutes", 75))
    tz = route[0].hours[0].local_time.tzinfo if route and route[0].hours else None
    if tz is None:
        return DayScore(day, None, None, None)
    m, _ = best_departure(route, day, routine["depart_home_window"], minutes, tz)
    e, _ = best_departure(list(reversed(route)), day, routine["depart_office_window"], minutes, tz)
    ms, es = (m.score if m else None), (e.score if e else None)
    score = (ms + es) / 2 if ms is not None and es is not None else None
    return DayScore(day, score, ms, es)


def recommend_office_days(route: list[Outlook], routine: dict, now: datetime) -> Recommendation:
    want = int(routine.get("office_days_per_week", 3))
    days, which = target_days(now, routine)
    scores = [score_day(route, d, routine) for d in days]
    known = sorted((s for s in scores if s.score is not None), key=lambda s: (s.score, s.day))
    unknown = [s for s in scores if s.score is None]

    reasons = [
        f"{s.day:%a %d %b}: leave ~{s.morning:.0f}, return ~{s.evening:.0f} → ~{s.score:.0f}"
        for s in sorted(known, key=lambda s: s.day)
    ] + [f"{s.day:%a %d %b}: no forecast yet" for s in unknown]

    if not known:
        return Recommendation("office_days", f"Office days ({which}): no forecast yet", reasons, ok=False)

    picks = sorted(known[:want], key=lambda s: s.day)
    headline = (f"Office days ({which}): {', '.join(s.label for s in picks)} look best "
                f"(commute ~{min(s.score for s in picks):.0f}–{max(s.score for s in picks):.0f})")
    rest = [s for s in known if s not in picks]
    if rest:
        worst = max(rest, key=lambda s: s.score)
        headline += f"; {worst.label} worst (~{worst.score:.0f})"
    if len(picks) < want and unknown:
        headline += f"; {', '.join(s.label for s in unknown)} not forecast yet"
    if len(days) < want:
        reasons.append(f"Only {len(days)} weekday(s) left {which}; Saans doesn't know which days "
                       "you've already been in.")
    return Recommendation("office_days", headline, reasons)
