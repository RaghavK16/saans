from __future__ import annotations

from datetime import timedelta

import respx

from saans.sources.firms import Firms
from tests.conftest import make_ctx

PUBLIC = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/"
AREA = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"


def _csv(fixtures_dir):
    return (fixtures_dir / "firms/J1_VIIRS_C2_South_Asia_sample.csv").read_bytes()


def test_without_key_uses_public_7d_files_on_first_run(ctx, fixtures_dir):
    with respx.mock:
        route = respx.get(url__startswith=PUBLIC).respond(200, content=_csv(fixtures_dir))
        recs = Firms().collect(ctx)
    urls = [str(c.request.url) for c in route.calls]
    assert len(urls) == 3 and all(u.endswith("_South_Asia_7d.csv") for u in urls)
    assert {u.split("/csv/")[1].split("_")[0] for u in urls} == {"SUOMI", "J1", "J2"}
    assert all(r.ok for r in recs)


def test_without_key_uses_48h_files_after_a_recent_run(config, fixtures_dir):
    ctx = make_ctx(config)
    with respx.mock:
        respx.get(url__startswith=PUBLIC).respond(200, content=_csv(fixtures_dir))
        Firms().collect(ctx)
    later = make_ctx(config, now=ctx.now + timedelta(hours=24))
    with respx.mock:
        route = respx.get(url__startswith=PUBLIC).respond(200, content=_csv(fixtures_dir))
        Firms().collect(later)
    assert all(str(c.request.url).endswith("_48h.csv") for c in route.calls)


def test_parse_filters_to_bbox_and_builds_utc_times(ctx, fixtures_dir):
    with respx.mock:
        respx.get(url__startswith=PUBLIC).respond(200, content=_csv(fixtures_dir))
        rec = Firms().collect(ctx)[1]
    rows = Firms().parse(rec, ctx.store.read_body(rec))
    assert len(rows) == 40  # 5 rows outside Punjab/Haryana bbox dropped
    r = rows[0]
    assert r["product"] == "VIIRS_NOAA20_NRT" and r["acquired_at"] == "2026-10-17T07:12:00Z"
    assert r["confidence"] == "nominal" and r["frp_mw"] == 7.4


def test_duplicate_detections_across_fetches_are_stored_once(ctx, fixtures_dir):
    src = Firms()
    with respx.mock:
        respx.get(url__startswith=PUBLIC).respond(200, content=_csv(fixtures_dir))
        recs = src.collect(ctx)
    inserted = sum(src.insert(ctx.conn, src.parse(r, ctx.store.read_body(r))) for r in recs)
    assert inserted == 40 * 3  # same fixture under 3 products = 3 distinct sets
    # same rows again under the same product -> nothing new
    again = src.parse(recs[1], ctx.store.read_body(recs[1]))
    assert src.insert(ctx.conn, again) == 0


def test_with_key_uses_area_api_and_chunks_long_gaps(ctx_with_keys, fixtures_dir):
    ctx_with_keys.config.sources["firms"]["products"] = ["VIIRS_NOAA20_NRT"]
    with respx.mock:
        route = respx.get(url__startswith=AREA).respond(200, content=_csv(fixtures_dir))
        recs = Firms().collect(ctx_with_keys)
    (call,) = route.calls  # first run: yesterday + today = one 2-day request
    assert str(call.request.url).endswith("/VIIRS_NOAA20_NRT/73.8,27.6,77.6,32.6/2/2026-10-17")
    assert "test-firms-key" not in recs[0].url

    later = make_ctx(ctx_with_keys.config, now=ctx_with_keys.now + timedelta(days=8))
    with respx.mock:
        route = respx.get(url__startswith=AREA).respond(200, content=_csv(fixtures_dir))
        Firms().collect(later)
    ranges = [str(c.request.url).rsplit("/", 2)[-2:] for c in route.calls]
    assert ranges == [["5", "2026-10-18"], ["4", "2026-10-23"]]  # 18th..26th, DAY_RANGE <= 5


def test_error_text_body_is_not_ok(ctx_with_keys):
    ctx_with_keys.config.sources["firms"]["products"] = ["VIIRS_NOAA20_NRT"]
    with respx.mock:
        respx.get(url__startswith=AREA).respond(200, text="Invalid MAP_KEY.")
        (rec,) = Firms().collect(ctx_with_keys)
    assert not rec.ok and "not FIRMS CSV" in rec.error
