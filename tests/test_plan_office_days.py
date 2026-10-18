from __future__ import annotations

from datetime import date

from saans.plan.office_days import recommend_office_days, target_days
from tests.plan_helpers import ROUTINE, at, outlook

MON = date(2026, 10, 19)
KEYS = ("home", "isbt", "ito", "dnd", "office")


def week_route(daily: dict[int, int | None], start: date = MON, days: int = 5):
    """Same value at every route point all day; daily = {weekday index from start: value}."""
    from datetime import datetime, timedelta

    from saans.config import Point
    from saans.plan.outlook import HourAir, Outlook
    from tests.plan_helpers import IST, aqi

    route = []
    for k in KEYS:
        hours = []
        for d in range(days):
            v = daily.get(d)
            for hh in range(24):
                t = datetime(start.year, start.month, start.day, hh, 30, tzinfo=IST) + timedelta(days=d)
                hours.append(HourAir(t, aqi(v), aqi(v)))
        route.append(Outlook(Point(k, k.title(), 28.7, 77.2), hours, (28.7, 77.2)))
    return route


def test_target_days():
    assert target_days(at(8, day=MON), ROUTINE) == ([date(2026, 10, d) for d in range(19, 24)], "this week")
    # after the morning window, today no longer counts
    assert target_days(at(12, day=MON), ROUTINE)[0][0] == date(2026, 10, 20)
    sunday = date(2026, 10, 18)
    assert target_days(at(17, day=sunday), ROUTINE) == ([date(2026, 10, d) for d in range(19, 24)], "next week")
    friday_evening = at(18, day=date(2026, 10, 23))
    assert target_days(friday_evening, ROUTINE)[1] == "next week"


def test_picks_the_three_cleanest_days_in_weekday_order():
    route = week_route({0: 150, 1: 120, 2: 210, 3: 130, 4: 140})
    r = recommend_office_days(route, ROUTINE, at(7, day=MON))
    assert r.headline == "Office days (this week): Tue, Thu, Fri look best (commute ~120–140); Wed worst (~210)"
    assert r.reasons[0] == "Mon 19 Oct: leave ~150, return ~150 → ~150"


def test_days_beyond_the_forecast_are_not_guessed():
    route = week_route({0: 150, 1: 120, 2: 210, 3: None, 4: None})
    r = recommend_office_days(route, ROUTINE, at(7, day=MON))
    assert r.headline.startswith("Office days (this week): Mon, Tue, Wed look best")
    assert r.reasons[-2:] == ["Thu 22 Oct: no forecast yet", "Fri 23 Oct: no forecast yet"]


def test_fewer_known_days_than_needed_says_what_is_missing():
    route = week_route({0: 150, 1: 120})
    r = recommend_office_days(route, ROUTINE, at(7, day=MON))
    assert r.headline.endswith("; Wed, Thu, Fri not forecast yet")


def test_late_in_the_week_notes_the_limit():
    thu = date(2026, 10, 22)
    route = week_route({0: 100, 1: 110}, start=thu, days=2)
    r = recommend_office_days(route, ROUTINE, at(7, day=thu))
    assert "Only 2 weekday(s) left this week" in r.reasons[-1]


def test_no_data():
    r = recommend_office_days(week_route({}), ROUTINE, at(7, day=MON))
    assert not r.ok and r.headline == "Office days (this week): no forecast yet"
