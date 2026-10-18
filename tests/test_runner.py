"""End-to-end: `saans run` against recorded responses for every source."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx

from saans import db, runner
from saans.cli import main
from saans.raw import RawStore
from saans.sources import cpcb_bulletin, datagovin, open_meteo

NOW = datetime(2026, 10, 18, 11, 56, tzinfo=timezone.utc)  # 17:26 IST
PDF = b"%PDF-1.7 synthetic"


def mock_all(router: respx.Router, fixtures_dir, *, fail: set[str] = frozenset()):
    def maybe(name, response):
        return httpx.Response(503) if name in fail else response

    router.get(open_meteo.AQ_URL).mock(return_value=maybe("aq", httpx.Response(
        200, content=(fixtures_dir / "open_meteo_aq/forecast.json").read_bytes())))
    router.get(open_meteo.WEATHER_URL).mock(return_value=maybe("weather", httpx.Response(
        200, content=(fixtures_dir / "open_meteo_weather/forecast.json").read_bytes())))
    router.get(url__startswith="https://firms.modaps.eosdis.nasa.gov/").mock(return_value=maybe(
        "firms", httpx.Response(200, content=(fixtures_dir / "firms/J1_VIIRS_C2_South_Asia_sample.csv").read_bytes())))
    router.get(cpcb_bulletin.URL).mock(return_value=maybe("bulletin", httpx.Response(
        200, content=PDF, headers={"content-type": "application/pdf"})))

    def dgi(request):
        city = request.url.params["filters[city]"]
        return maybe("datagovin", httpx.Response(
            200, content=(fixtures_dir / f"datagovin/{city.lower()}_page.json").read_bytes()))
    router.get(datagovin.URL).mock(side_effect=dgi)


@pytest.fixture
def fast(config):
    config.sources["cpcb_bulletin"].update(delay_seconds=0, max_per_run=3)
    return config


def _run(config, fixtures_dir, command="run", **kw):
    with respx.mock(assert_all_called=False) as router:
        mock_all(router, fixtures_dir, **kw)
        ctx = runner.open_context(config, command, clock=lambda: NOW)
        outcomes = runner.collect(ctx)
        status = runner.finish(ctx, outcomes)
    return ctx, {o.source: o for o in outcomes}, status


def test_run_without_keys_collects_keyless_sources_and_skips_the_rest(fast, fixtures_dir):
    ctx, out, status = _run(fast, fixtures_dir)
    assert status == "ok"
    assert out["datagovin"].status == "skipped"
    assert {k: o.status for k, o in out.items() if k != "datagovin"} == {
        "open_meteo_aq": "ok", "open_meteo_weather": "ok", "firms": "ok", "cpcb_bulletin": "ok"}
    assert out["open_meteo_aq"].row_count == 720
    assert out["firms"].row_count == 120 and out["cpcb_bulletin"].raw_count == 3
    run = ctx.conn.execute("SELECT status, finished_at FROM runs WHERE id = ?", (ctx.run_id,)).fetchone()
    assert run["status"] == "ok" and run["finished_at"]


def test_run_with_keys_also_collects_stations(config_with_keys, fixtures_dir):
    config_with_keys.sources["cpcb_bulletin"].update(delay_seconds=0, max_per_run=1)
    ctx, out, status = _run(config_with_keys, fixtures_dir)
    # Fixture pages hold 10 rows but report total=406 (Delhi) / 28 (Noida), so the collector
    # pages on: Delhi stops at the 10-page safety cap, Noida after 3 pages.
    offsets = [(r[0], r[1]) for r in ctx.conn.execute(
        "SELECT json_extract(params_json, '$.city'), json_extract(params_json, '$.offset') "
        "FROM raw_responses WHERE source = 'datagovin' ORDER BY id")]
    assert offsets == [("Delhi", o) for o in range(0, 100, 10)] + [("Noida", o) for o in (0, 10, 20)]
    assert out["datagovin"].status == "ok" and out["datagovin"].row_count == 130
    assert status == "ok"
    urls = [r[0] for r in ctx.conn.execute("SELECT url FROM raw_responses")]
    assert not any("test-dgi-key" in u or "test-firms-key" in u for u in urls)


def test_one_failing_source_makes_the_run_partial_not_broken(fast, fixtures_dir):
    _, out, status = _run(fast, fixtures_dir, fail={"aq"})
    assert out["open_meteo_aq"].status == "failed" and "HTTP 503" in out["open_meteo_aq"].detail
    assert out["open_meteo_weather"].status == "ok"
    assert status == "partial"


def test_everything_failing_is_a_failed_run(fast, fixtures_dir):
    _, _, status = _run(fast, fixtures_dir, fail={"aq", "weather", "firms", "bulletin"})
    assert status == "failed"


def test_a_crashing_source_is_contained(fast, fixtures_dir, monkeypatch):
    def boom(self, ctx):
        raise RuntimeError("bug in collector")
    monkeypatch.setattr(open_meteo.OpenMeteoWeather, "collect", boom)
    _, out, status = _run(fast, fixtures_dir)
    assert out["open_meteo_weather"].status == "failed" and "bug in collector" in out["open_meteo_weather"].detail
    assert out["open_meteo_aq"].status == "ok" and status == "partial"


def test_reparse_rebuilds_identical_tables(config_with_keys, fixtures_dir):
    config_with_keys.sources["cpcb_bulletin"].update(delay_seconds=0, max_per_run=1)
    ctx, _, _ = _run(config_with_keys, fixtures_dir)

    def snapshot():
        return {t: ctx.conn.execute(f"SELECT * FROM {t} ORDER BY 1,2,3,4").fetchall() for t in db.PARSED_TABLES}

    before = {t: [tuple(r) for r in rows] for t, rows in snapshot().items()}
    counts = runner.reparse(ctx.conn, RawStore(ctx.conn, config_with_keys.raw_dir, []))
    after = {t: [tuple(r) for r in rows] for t, rows in snapshot().items()}
    assert after == before and all(counts[t] > 0 for t in db.PARSED_TABLES)


def test_cli_run_writes_brief_and_exits_zero(fast, fixtures_dir, monkeypatch, capsys):
    fast_path = fast.root / "config.yaml"
    import yaml
    data = yaml.safe_load(fast_path.read_text())
    data["sources"]["cpcb_bulletin"].update(delay_seconds=0, max_per_run=2)
    fast_path.write_text(yaml.safe_dump(data, allow_unicode=True))
    monkeypatch.setattr(runner, "utcnow", lambda: NOW)
    with respx.mock(assert_all_called=False) as router:
        mock_all(router, fixtures_dir)
        code = main(["--config", str(fast_path), "run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "skipped  datagovin" in out and "run 1: ok" in out
    assert (fast.out_dir / "brief-2026-10-18.md").exists()
    assert (fast.out_dir / "brief-2026-10-18.html").exists()


def test_cli_backfill_unknown_source(fast, capsys):
    assert main(["--config", str(fast.root / "config.yaml"), "backfill", "nope"]) == 2
