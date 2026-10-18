"""Home air: when windows can open, when the purifier must run, and when to close up.

There is no indoor sensor (out of scope for v1), so this is outdoor-driven advice:
- Windows can open during waking hours when instant NAQI <= windows_open_max.
- Otherwise the purifier runs. A spike (instant NAQI reaching spike_alert_above) gets a
  "close up and run on high from HH:MM" call.
- Horizon: from now until 07:00 tomorrow, so the evening run covers the night.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from saans.plan.outlook import HourAir, Outlook, best, worst
from saans.plan.rules import Recommendation, describe, fmt_window, value_range

WAKING = (time(6, 0), time(23, 0))  # rows starting in this range can have windows open
NIGHT_START = time(22, 0)
MORNING_END = time(7, 0)


def _runs(hours: list[HourAir]) -> list[list[HourAir]]:
    """Group contiguous rows."""
    runs: list[list[HourAir]] = []
    for h in hours:
        if runs and runs[-1][-1].end == h.local_time:
            runs[-1].append(h)
        else:
            runs.append([h])
    return runs


def recommend_home_air(home: Outlook, thresholds: dict, now: datetime) -> Recommendation:
    open_max = thresholds.get("windows_open_max", 100)
    spike_at = thresholds.get("spike_alert_above", 200)
    until = datetime.combine(now.date() + timedelta(days=1), MORNING_END, now.tzinfo)
    horizon = [h for h in home.hours if h.end > now and h.local_time < until and h.instant.valid]
    if not horizon:
        return Recommendation("home_air", "Windows: no forecast; keep them closed and run the purifier",
                              ok=False)

    waking = [h for h in horizon if WAKING[0] <= h.local_time.time() <= WAKING[1]
              and h.local_time.date() == now.date()]
    clean = [h for h in waking if h.instant.value <= open_max]
    open_runs = _runs(clean)

    reasons = []
    if open_runs:
        # a run already under way starts "now", not at the top of its forecast hour
        spans = [fmt_window(max(r[0].local_time, now), r[-1].end) for r in open_runs]
        shown = " and ".join(spans[:2]) + (f" (+{len(spans) - 2} more)" if len(spans) > 2 else "")
        headline = f"Windows: open {shown}; purifier on otherwise"
        for r, label in zip(open_runs, spans):
            reasons.append(f"{label}: instant NAQI {value_range(r)}, at or below {open_max:.0f}")
    else:
        b = best(waking) or best(horizon)
        headline = "Windows: keep closed; purifier on"
        reasons.append(f"No waking hour at or below {open_max:.0f}; the cleanest is "
                       f"{b.local_time:%H:%M} ({describe(b)})")

    spike = next((h for h in horizon if h.instant.value >= spike_at), None)
    if spike:
        peak = worst(h for h in horizon if h.local_time >= spike.local_time)
        headline += f", on high from {spike.local_time:%H:%M}"
        reasons.append(f"Spike: instant NAQI reaches {spike.instant.value} at {spike.local_time:%H:%M}, "
                       f"peaking at {peak.instant.value} ({peak.local_time:%H:%M}, "
                       f"{'/'.join(peak.instant.prominent)}). Close windows before then.")

    night = [h for h in horizon if h.local_time.time() >= NIGHT_START or h.local_time.date() > now.date()]
    if night:
        n = worst(night)
        reasons.append(f"Overnight: up to {n.instant.value} ({n.instant.category}) at "
                       f"{n.local_time:%H:%M}; keep the bedroom purifier on"
                       if n.instant.value > open_max else
                       f"Overnight: stays at or below {n.instant.value}")
    return Recommendation("home_air", headline, reasons)
