from __future__ import annotations

from saans.plan.home_air import recommend_home_air
from tests.plan_helpers import THRESHOLDS, at, outlook


def rec(values, now=at(6), default=150, days=2):
    return recommend_home_air(outlook("home", values, default=default, days=days), THRESHOLDS, now)


def test_clean_afternoon_opens_windows_for_that_run():
    r = rec({13: 90, 14: 80, 15: 95})
    assert r.headline == "Windows: open 13:30–16:30; purifier on otherwise"
    assert r.reasons[0] == "13:30–16:30: instant NAQI 80–95, at or below 100"


def test_two_runs_are_listed_and_more_are_counted():
    r = rec({6: 90, 10: 90, 13: 90, 17: 90})
    assert r.headline.startswith("Windows: open 06:30–07:30 and 10:30–11:30 (+2 more)")


def test_smog_day_keeps_windows_closed_and_names_the_cleanest_hour():
    r = rec({13: 120}, default=180)
    assert r.headline == "Windows: keep closed; purifier on"
    assert "the cleanest is 13:30 (120 Moderate, PM2.5)" in r.reasons[0]


def test_evening_spike_triggers_close_up_call():
    r = rec({21: 210, 22: 260, 23: 280}, default=140)
    assert r.headline == "Windows: keep closed; purifier on, on high from 21:30"
    spike = next(x for x in r.reasons if x.startswith("Spike"))
    assert "reaches 210 at 21:30, peaking at 280 (23:30" in spike


def test_overnight_is_covered_until_7am_tomorrow():
    r = rec({}, default=90, now=at(21))
    # the 20:30 row is under way at 21:00, so the run starts now; tomorrow counts as night only
    assert r.headline.startswith("Windows: open 21:00–23:30")
    assert r.reasons[-1] == "Overnight: stays at or below 90"


def test_past_hours_are_ignored():
    r = rec({7: 50, 8: 50}, now=at(12))
    assert "07:30" not in r.headline and r.headline.startswith("Windows: keep closed")


def test_no_data():
    r = rec({}, default=None)
    assert not r.ok and "no forecast" in r.headline
