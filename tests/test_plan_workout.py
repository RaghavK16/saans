from __future__ import annotations

from saans.plan.workout import GYM, LIGHT, OUTDOORS, recommend_workout, verdict
from tests.plan_helpers import ROUTINE, THRESHOLDS, at, outlook


def rec(values, now=at(6), **kw):
    return recommend_workout(outlook("home", values, **kw), ROUTINE, THRESHOLDS, now)


def test_verdict_thresholds_are_inclusive():
    assert [verdict(v, THRESHOLDS) for v in (100, 101, 150, 151)] == [OUTDOORS, LIGHT, LIGHT, GYM]


def test_clean_day_picks_the_cleaner_slot_outdoors():
    # slot 08-09 overlaps the 07:30 and 08:30 rows; 20-21 overlaps 19:30 and 20:30
    r = rec({7: 90, 8: 95, 19: 60, 20: 70})
    assert r.headline == "Workout: outdoors 20:00–21:00 (NAQI up to 70)"
    assert "08:00–09:00: instant NAQI 90–95" in r.reasons[0] and r.reasons[0].endswith("→ outdoors")


def test_slot_is_judged_by_its_worst_hour():
    r = rec({7: 40, 8: 160, 19: 120, 20: 130})
    assert r.headline == "Workout: outdoors but easy and short, 20:00–21:00 (NAQI up to 130)"


def test_smog_day_sends_you_to_the_gym_and_names_the_less_bad_slot():
    r = rec({7: 310, 8: 290, 19: 240, 20: 260})
    assert r.headline == ("Workout: gym; outdoor NAQI reaches 260 (least bad 20:00–21:00), "
                          "above your 150 limit for training outside")
    assert all("→ gym" in line for line in r.reasons)


def test_ties_go_to_the_earlier_slot():
    assert "08:00–09:00" in rec({7: 80, 8: 80, 19: 80, 20: 80}).headline


def test_past_slots_are_skipped():
    r = rec({7: 50, 8: 50, 19: 180, 20: 190}, now=at(12))
    assert r.reasons[0] == "08:00–09:00: already passed"
    assert r.headline.startswith("Workout: gym; outdoor NAQI reaches 190 (20:00–21:00)")


def test_after_last_slot_the_advice_is_for_tomorrow():
    r = rec({}, now=at(21, 30), default=80, days=2)
    assert r.headline == "Workout tomorrow: outdoors 08:00–09:00 (NAQI up to 80)"


def test_missing_data_is_flagged_not_guessed():
    r = rec({}, default=None)
    assert not r.ok and "no forecast" in r.headline
    assert r.reasons == ["08:00–09:00: no forecast", "20:00–21:00: no forecast"]
