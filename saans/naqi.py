"""India's CPCB National Air Quality Index (NAQI, 2014).

Breakpoints are from CPCB's NAQI table (cross-checked 2026-10-18, see DECISIONS.md D-012).
Sub-index for a concentration C in band [BLO, BHI] mapping to index band [ILO, IHI]:

    I = (IHI - ILO) / (BHI - BLO) * (C - BLO) + ILO

Choices this module makes that the CPCB table leaves open (all documented in D-012):
- Concentrations are rounded half-up to the table's precision (integers; 1 decimal for CO
  and Pb) before lookup, so values like 30.4 vs 30.6 land in a band, as CPCB's integer
  ranges imply.
- The Severe band has no upper concentration. We extrapolate it with the width of the
  Very Poor band and cap the index at 500.
- Overall AQI requires >= 3 pollutants including PM2.5 or PM10, and is the max sub-index.
- "Official" averaging: 24 h mean (>= 16 hourly values) for PM10/PM2.5/NO2/SO2/NH3/Pb,
  8 h mean (>= 6 values) for CO/O3. "Instant": NAQI breakpoints applied to a single hour,
  which is NOT an official number and must always be labelled as such (D-002).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum


class Pollutant(StrEnum):
    PM10 = "PM10"
    PM25 = "PM2.5"
    NO2 = "NO2"
    O3 = "O3"
    CO = "CO"  # mg/m3; every other pollutant is ug/m3
    SO2 = "SO2"
    NH3 = "NH3"
    PB = "Pb"


INDEX_BANDS: tuple[tuple[int, int], ...] = (
    (0, 50), (51, 100), (101, 200), (201, 300), (301, 400), (401, 500),
)
CATEGORIES = ("Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe")

# Concentration bands per pollutant, aligned with INDEX_BANDS. Severe's upper bound is None.
BREAKPOINTS: dict[Pollutant, tuple[tuple[float, float | None], ...]] = {
    Pollutant.PM10: ((0, 50), (51, 100), (101, 250), (251, 350), (351, 430), (431, None)),
    Pollutant.PM25: ((0, 30), (31, 60), (61, 90), (91, 120), (121, 250), (251, None)),
    Pollutant.NO2: ((0, 40), (41, 80), (81, 180), (181, 280), (281, 400), (401, None)),
    Pollutant.O3: ((0, 50), (51, 100), (101, 168), (169, 208), (209, 748), (749, None)),
    Pollutant.CO: ((0, 1.0), (1.1, 2.0), (2.1, 10), (10.1, 17), (17.1, 34), (34.1, None)),
    Pollutant.SO2: ((0, 40), (41, 80), (81, 380), (381, 800), (801, 1600), (1601, None)),
    Pollutant.NH3: ((0, 200), (201, 400), (401, 800), (801, 1200), (1201, 1800), (1801, None)),
    Pollutant.PB: ((0, 0.5), (0.6, 1.0), (1.1, 2.0), (2.1, 3.0), (3.1, 3.5), (3.6, None)),
}

DECIMALS = {p: (1 if p in (Pollutant.CO, Pollutant.PB) else 0) for p in Pollutant}
AVERAGING_HOURS = {p: (8 if p in (Pollutant.CO, Pollutant.O3) else 24) for p in Pollutant}
MIN_HOURS = {24: 16, 8: 6}
PARTICULATES = (Pollutant.PM25, Pollutant.PM10)


def _round_half_up(x: float, decimals: int) -> float:
    q = Decimal(1).scaleb(-decimals)
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))


def sub_index(pollutant: Pollutant, concentration: float | None) -> int | None:
    """NAQI sub-index (0-500) for one pollutant's averaged concentration."""
    if concentration is None:
        return None
    if concentration < 0:
        raise ValueError(f"negative concentration for {pollutant}: {concentration}")
    c = _round_half_up(concentration, DECIMALS[pollutant])
    bands = BREAKPOINTS[pollutant]
    for i, (blo, bhi) in enumerate(bands):
        if bhi is None:  # Severe: extrapolate with the Very Poor band's width
            vp_lo, vp_hi = bands[i - 1]
            bhi = blo + (vp_hi - vp_lo)  # type: ignore[operator]
            if c >= bhi:
                return 500
        if c <= bhi:
            ilo, ihi = INDEX_BANDS[i]
            value = (ihi - ilo) / (bhi - blo) * (max(c, blo) - blo) + ilo
            return int(_round_half_up(value, 0))
    raise AssertionError("unreachable")  # pragma: no cover


def category(aqi: int) -> str:
    for (lo, hi), name in zip(INDEX_BANDS, CATEGORIES):
        if aqi <= hi:
            return name
    return CATEGORIES[-1]


@dataclass(frozen=True)
class AqiResult:
    value: int | None
    category: str | None
    prominent: tuple[Pollutant, ...]
    sub_indices: dict[Pollutant, int]

    @property
    def valid(self) -> bool:
        return self.value is not None


def overall(concentrations: Mapping[Pollutant, float | None]) -> AqiResult:
    """Overall NAQI from (already averaged) concentrations."""
    subs = {p: si for p, c in concentrations.items() if (si := sub_index(p, c)) is not None}
    enough = len(subs) >= 3 and any(p in subs for p in PARTICULATES)
    if not enough:
        return AqiResult(None, None, (), subs)
    value = max(subs.values())
    prominent = tuple(p for p in Pollutant if subs.get(p) == value)
    return AqiResult(value, category(value), prominent, subs)


HourlySeries = Mapping[datetime, Mapping[Pollutant, float | None]]


def official_concentrations(series: HourlySeries, at: datetime) -> dict[Pollutant, float | None]:
    """CPCB-style averages ending at `at` (inclusive): 24 h or 8 h, with minimum coverage."""
    out: dict[Pollutant, float | None] = {}
    pollutants = {p for hour in series.values() for p in hour}
    for p in pollutants:
        window = AVERAGING_HOURS[p]
        values = [
            v
            for h in range(window)
            if (v := series.get(at - timedelta(hours=h), {}).get(p)) is not None
        ]
        out[p] = sum(values) / len(values) if len(values) >= MIN_HOURS[window] else None
    return out


def official(series: HourlySeries, at: datetime) -> AqiResult:
    return overall(official_concentrations(series, at))


def instant(series: HourlySeries, at: datetime) -> AqiResult:
    """Breakpoints applied to one hour's concentrations. Not official: label it 'instant'."""
    return overall(series.get(at, {}))
