from __future__ import annotations

import httpx
import respx

from saans.sources.open_meteo import AQ_URL, WEATHER_URL, OpenMeteoAirQuality, OpenMeteoWeather


def _collect_and_parse(ctx, source, url, fixture):
    with respx.mock:
        route = respx.get(url).respond(200, content=fixture.read_bytes(),
                                       headers={"content-type": "application/json"})
        (raw,) = source.collect(ctx)
    assert raw.ok, raw.error
    rows = source.parse(raw, ctx.store.read_body(raw))
    return route, raw, rows


def test_aq_collect_requests_all_points_in_one_call(ctx, fixtures_dir):
    src = OpenMeteoAirQuality()
    route, raw, rows = _collect_and_parse(ctx, src, AQ_URL, fixtures_dir / "open_meteo_aq/forecast.json")
    q = route.calls.last.request.url.params
    assert q["latitude"] == "28.72,28.57,28.67,28.63,28.58"
    assert q["longitude"] == "77.19,77.32,77.23,77.24,77.27"
    assert "carbon_monoxide" in q["hourly"]
    assert raw.params["location_keys"] == ["home", "office", "isbt", "ito", "dnd"]
    assert len(rows) == 5 * 144  # 5 points x (1 past + 5 forecast days) x 24 h


def test_aq_parse_converts_units_and_times(ctx, fixtures_dir):
    _, raw, rows = _collect_and_parse(
        ctx, OpenMeteoAirQuality(), AQ_URL, fixtures_dir / "open_meteo_aq/forecast.json")
    home = [r for r in rows if r["location_key"] == "home"]
    assert home[0]["valid_at"].endswith(":00:00Z")
    assert home[0]["issued_at"] == raw.fetched_at == "2026-10-18T11:56:00Z"
    co = [r["co_mgm3"] for r in home if r["co_mgm3"] is not None]
    assert co and max(co) < 50  # mg/m3, not ug/m3
    assert any(r["pm25_ugm3"] for r in home)


def test_aq_insert_is_idempotent(ctx, fixtures_dir):
    src = OpenMeteoAirQuality()
    _, raw, rows = _collect_and_parse(ctx, src, AQ_URL, fixtures_dir / "open_meteo_aq/forecast.json")
    assert src.insert(ctx.conn, rows) == len(rows)
    assert src.insert(ctx.conn, rows) == 0


def test_weather_parse_has_upper_level_wind(ctx, fixtures_dir):
    src = OpenMeteoWeather()
    route, raw, rows = _collect_and_parse(
        ctx, src, WEATHER_URL, fixtures_dir / "open_meteo_weather/forecast.json")
    keys = raw.params["location_keys"]
    assert keys[:2] == ["amritsar", "bathinda"] and keys[-2:] == ["home", "office"]
    assert len(rows) == len(keys) * 96
    ludhiana = [r for r in rows if r["location_key"] == "ludhiana"]
    assert all(0 <= r["wind_dir_850_deg"] <= 360 for r in ludhiana if r["wind_dir_850_deg"] is not None)


def test_api_error_is_recorded_not_raised(ctx):
    with respx.mock:
        respx.get(AQ_URL).respond(400, json={"error": True, "reason": "Latitude must be in range"})
        (raw,) = OpenMeteoAirQuality().collect(ctx)
    assert not raw.ok and raw.error == "HTTP 400"


def test_timeout_is_recorded_not_raised(ctx):
    with respx.mock:
        respx.get(AQ_URL).mock(side_effect=httpx.ReadTimeout("slow"))
        (raw,) = OpenMeteoAirQuality().collect(ctx)
    assert not raw.ok and "ReadTimeout" in raw.error
