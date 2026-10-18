from __future__ import annotations

from datetime import date

from saans.plan.commute import evaluate, recirculation, recommend_commute
from tests.plan_helpers import ROUTINE, THRESHOLDS, at, outlook

SUNDAY = date(2026, 10, 18)


def route(**values_by_point):
    """home, isbt, ito, dnd, office; each takes {hour: value} or an int default."""
    keys = ["home", "isbt", "ito", "dnd", "office"]
    out = []
    for k in keys:
        v = values_by_point.get(k, 90)
        out.append(outlook(k, v if isinstance(v, dict) else {}, default=v if isinstance(v, int) else 90, days=2))
    return out


def test_samples_are_spread_over_the_drive():
    dep = evaluate(route(), at(9, 30), 75)
    assert [s.passes_at.strftime("%H:%M") for s in dep.samples] == ["09:30", "09:48", "10:07", "10:26", "10:45"]
    assert [s.place for s in dep.samples] == ["Home", "Isbt", "Ito", "Dnd", "Office"]


def test_picks_the_least_bad_departure_and_quantifies_the_saving():
    # mornings: 08:30-09:30 rows bad everywhere, 10:30 row clean
    bad_early = {8: 220, 9: 200, 10: 110, 11: 110}
    r = recommend_commute(route(home=bad_early, isbt=bad_early, ito=bad_early, dnd=bad_early, office=bad_early),
                          ROUTINE, THRESHOLDS, at(7))
    morning = r.reasons[0]
    assert morning.startswith("Morning: leave 10:30 (route NAQI ~110")
    assert any("instead of 09:00 cuts route NAQI" in x for x in r.reasons)
    assert "leave 10:30" in r.headline and r.headline.startswith("Commute (if you go in):")


def test_recirculation_calls():
    clean = evaluate(route(), at(9), 75)
    assert recirculation(clean, 100) == "fresh-air mode is fine"
    dirty_end = evaluate(route(ito=150, dnd=160, office=170), at(9), 75)
    assert recirculation(dirty_end, 100) == "recirculate from Ito onward"
    patchy = evaluate(route(isbt=150), at(9), 75)
    assert recirculation(patchy, 100) == "recirculate around Isbt"
    all_bad = evaluate(route(home=120, isbt=130, ito=140, dnd=150, office=160), at(9), 75)
    assert recirculation(all_bad, 100) == "recirculate the whole way"


def test_co2_tip_only_when_recirculating():
    dirty = recommend_commute(route(home=150, isbt=150, ito=150, dnd=150, office=150), ROUTINE, THRESHOLDS, at(7))
    assert any("CO₂" in x for x in dirty.reasons)
    clean = recommend_commute(route(), ROUTINE, THRESHOLDS, at(7))
    assert not any("CO₂" in x for x in clean.reasons)


def test_after_the_morning_window_only_the_return_is_advised():
    r = recommend_commute(route(), ROUTINE, THRESHOLDS, at(12))
    assert r.reasons[0] == "Morning: window 09:00-10:30 has passed"
    assert r.headline.startswith("Commute (if you go in): return any time 16:30–18:30")


def test_after_the_evening_window_advice_is_for_tomorrow():
    r = recommend_commute(route(), ROUTINE, THRESHOLDS, at(19))
    assert r.headline.startswith("Commute tomorrow (if you go in): any time 09:00–10:30")


def test_weekend():
    r = recommend_commute(route(), ROUTINE, THRESHOLDS, at(8, day=SUNDAY))
    assert r.headline == "Commute: none (weekend)"


def test_coarse_grid_is_disclosed():
    r = recommend_commute(route(), ROUTINE, THRESHOLDS, at(7))
    assert "5 route points fall in 1 forecast grid cells" in r.reasons[-1]


def test_no_data():
    empty = [outlook(k, default=None) for k in ("home", "isbt", "ito", "dnd", "office")]
    r = recommend_commute(empty, ROUTINE, THRESHOLDS, at(7))
    assert not r.ok and "no forecast" in r.headline


def test_mostly_bad_route_is_called_whole_way():
    dep = evaluate(route(home=150, isbt=150, ito=80, dnd=150, office=150), at(9), 75)
    assert recirculation(dep, 100) == "recirculate the whole way (cleaner only near Ito)"


def test_flat_departures_are_not_given_false_precision():
    r = recommend_commute(route(), ROUTINE, THRESHOLDS, at(7))
    assert r.headline.startswith("Commute (if you go in): any time 09:00–10:30 (~90")
    assert any("timing barely matters" in x for x in r.reasons)


def test_short_names():
    from saans.plan.commute import short_name
    assert short_name("Model Town, Delhi") == "Model Town"
    assert short_name("Noida (sector not set — edit me)") == "Noida"
