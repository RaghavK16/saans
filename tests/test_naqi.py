from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from saans import naqi
from saans.naqi import BREAKPOINTS, INDEX_BANDS, Pollutant, sub_index

P = Pollutant

# ---------------------------------------------------------------- breakpoint boundaries

BOUNDARY_CASES = [
    pytest.param(p, blo, ilo, id=f"{p}-band{i}-low")
    for p, bands in BREAKPOINTS.items()
    for i, ((blo, _), (ilo, _)) in enumerate(zip(bands, INDEX_BANDS))
] + [
    pytest.param(p, bhi, ihi, id=f"{p}-band{i}-high")
    for p, bands in BREAKPOINTS.items()
    for i, ((_, bhi), (_, ihi)) in enumerate(zip(bands, INDEX_BANDS))
    if bhi is not None
]


@pytest.mark.parametrize("pollutant, concentration, expected", BOUNDARY_CASES)
def test_every_band_edge_maps_to_its_index_edge(pollutant, concentration, expected):
    assert sub_index(pollutant, concentration) == expected


def test_table_is_complete_and_monotonic():
    assert set(BREAKPOINTS) == set(Pollutant)
    for p, bands in BREAKPOINTS.items():
        assert len(bands) == len(INDEX_BANDS) == 6
        edges = [x for band in bands for x in band if x is not None]
        assert edges == sorted(edges), p


# ---------------------------------------------------------------- worked examples

@pytest.mark.parametrize(
    "pollutant, concentration, expected",
    [
        (P.PM25, 75, 149),    # (200-101)/(90-61)*(75-61)+101 = 148.79
        (P.PM25, 45, 75),     # (100-51)/(60-31)*(45-31)+51 = 74.66
        (P.PM10, 300, 250),   # (300-201)/(350-251)*(300-251)+201
        (P.PM10, 175, 150),   # (200-101)/(250-101)*(175-101)+101 = 150.17
        (P.CO, 5.0, 137),     # (200-101)/(10-2.1)*(5-2.1)+101 = 137.34
        (P.O3, 180, 229),     # (300-201)/(208-169)*(180-169)+201 = 228.92
    ],
)
def test_worked_examples(pollutant, concentration, expected):
    assert sub_index(pollutant, concentration) == expected


# ---------------------------------------------------------------- rounding & gaps

@pytest.mark.parametrize(
    "pollutant, concentration, expected",
    [
        (P.PM25, 30.4, 50),   # rounds to 30 -> Good
        (P.PM25, 30.5, 51),   # rounds half-up to 31 -> Satisfactory (no gap between bands)
        (P.CO, 1.04, 50),
        (P.CO, 1.05, 51),
        (P.PB, 0.55, 51),
        (P.PM10, 0, 0),
    ],
)
def test_rounding_closes_the_gaps_between_integer_bands(pollutant, concentration, expected):
    assert sub_index(pollutant, concentration) == expected


def test_severe_band_extrapolates_then_caps_at_500():
    # PM2.5 Severe starts at 251; Very Poor width is 250-121 = 129, so 500 is reached at 380.
    assert sub_index(P.PM25, 251) == 401
    assert sub_index(P.PM25, 315.5) == 451  # rounds to 316: (500-401)/129*(316-251)+401 = 450.88
    assert sub_index(P.PM25, 380) == 500
    assert sub_index(P.PM25, 999) == 500


def test_none_and_negative():
    assert sub_index(P.PM25, None) is None
    with pytest.raises(ValueError):
        sub_index(P.PM25, -1)


# ---------------------------------------------------------------- categories

@pytest.mark.parametrize(
    "aqi, name",
    [(0, "Good"), (50, "Good"), (51, "Satisfactory"), (100, "Satisfactory"), (101, "Moderate"),
     (200, "Moderate"), (201, "Poor"), (300, "Poor"), (301, "Very Poor"), (400, "Very Poor"),
     (401, "Severe"), (500, "Severe"), (650, "Severe")],
)
def test_category_edges(aqi, name):
    assert naqi.category(aqi) == name


# ---------------------------------------------------------------- overall AQI rules

def test_overall_is_max_sub_index_with_prominent_pollutant():
    r = naqi.overall({P.PM25: 75, P.PM10: 175, P.NO2: 30})
    assert (r.value, r.category, r.prominent) == (150, "Moderate", (P.PM10,))
    assert r.sub_indices[P.PM25] == 149


def test_overall_reports_ties_as_joint_prominent():
    r = naqi.overall({P.PM25: 31, P.O3: 51, P.NO2: 10})
    assert r.value == 51 and r.prominent == (P.PM25, P.O3)


def test_overall_needs_three_pollutants():
    r = naqi.overall({P.PM25: 75, P.PM10: 175, P.NO2: None})
    assert not r.valid and r.sub_indices == {P.PM25: 149, P.PM10: 150}


def test_overall_needs_a_particulate():
    assert not naqi.overall({P.NO2: 30, P.SO2: 10, P.O3: 40}).valid


# ---------------------------------------------------------------- averaging

T0 = datetime(2026, 10, 18, 0, tzinfo=timezone.utc)


def _series(hours: int, values: dict[Pollutant, float], skip: set[int] = frozenset()):
    return {
        T0 + timedelta(hours=h): dict(values) for h in range(hours) if h not in skip
    }


def test_official_uses_24h_and_8h_windows():
    series = _series(24, {P.PM25: 60, P.PM10: 100, P.CO: 1.0})
    # make the latest 8 h of CO much higher; the 24 h pollutants stay put
    for h in range(16, 24):
        series[T0 + timedelta(hours=h)][P.CO] = 3.0
    conc = naqi.official_concentrations(series, T0 + timedelta(hours=23))
    assert conc[P.PM25] == 60 and conc[P.CO] == 3.0


def test_official_requires_minimum_coverage():
    at = T0 + timedelta(hours=23)
    sparse = _series(24, {P.PM25: 60}, skip=set(range(9)))  # 15 of 24 hours
    assert naqi.official_concentrations(sparse, at)[P.PM25] is None
    ok = _series(24, {P.PM25: 60}, skip=set(range(8)))  # 16 of 24 hours
    assert naqi.official_concentrations(ok, at)[P.PM25] == 60
    co = _series(24, {P.CO: 1.0}, skip={22, 23, 21})  # 5 of last 8 hours
    assert naqi.official_concentrations(co, at)[P.CO] is None


def test_instant_reads_a_single_hour():
    series = _series(3, {P.PM25: 30, P.PM10: 50, P.NO2: 40})
    series[T0 + timedelta(hours=2)][P.PM25] = 250
    assert naqi.instant(series, T0 + timedelta(hours=2)).value == 400
    assert naqi.official(series, T0 + timedelta(hours=2)).valid is False  # not enough hours
    assert naqi.instant(series, T0 + timedelta(hours=99)).valid is False
