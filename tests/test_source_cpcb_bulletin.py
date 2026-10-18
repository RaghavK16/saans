from __future__ import annotations

import base64
from datetime import date, datetime, timezone

import pytest
import respx

from saans.sources.cpcb_bulletin import (
    NOT_PUBLISHED, URL, CpcbBulletin, bulletin_id, latest_expected,
)
from tests.conftest import make_ctx

FAKE_PDF = b"%PDF-1.7\n% tiny synthetic stand-in; real PDFs arrive with Phase 4 parsing\n"


def _requested_date(request) -> str:
    path = base64.b64decode(request.url.params["id"]).decode()
    return f"{path[-12:-8]}-{path[-8:-6]}-{path[-6:-4]}"


@pytest.fixture
def short_backfill(config):
    config.sources["cpcb_bulletin"].update(backfill_start="2026-10-10", max_per_run=3)
    return config


def test_bulletin_id_matches_the_observed_scheme():
    assert bulletin_id(date(2026, 10, 17)) == "RG93bmxvYWRzL0FRSV9CdWxsZXRpbl8yMDI2MTAxNy5wZGY="


@pytest.mark.parametrize("ist_time, expected", [
    ("2026-10-18T16:29:00+05:30", date(2026, 10, 17)),
    ("2026-10-18T16:30:00+05:30", date(2026, 10, 18)),
    ("2026-10-18T00:10:00+05:30", date(2026, 10, 17)),
])
def test_latest_expected_respects_the_4pm_publication(ist_time, expected):
    assert latest_expected(datetime.fromisoformat(ist_time)) == expected


def test_collect_fetches_newest_first_up_to_the_cap(short_backfill):
    ctx = make_ctx(short_backfill)  # 17:26 IST on 18 Oct -> today's bulletin is expected
    sleeps = []
    ctx.sleep = sleeps.append
    with respx.mock:
        route = respx.get(URL).respond(200, content=FAKE_PDF, headers={"content-type": "application/pdf"})
        recs = CpcbBulletin().collect(ctx)
    assert [_requested_date(c.request) for c in route.calls] == ["2026-10-18", "2026-10-17", "2026-10-16"]
    assert all(r.ok for r in recs) and [r.request_key for r in recs][0] == "2026-10-18"
    assert sleeps == [1.0, 1.0]  # polite delay between requests, not before the first


def test_collect_skips_dates_already_stored(short_backfill):
    ctx = make_ctx(short_backfill)
    src = CpcbBulletin()
    with respx.mock:
        respx.get(URL).respond(200, content=FAKE_PDF, headers={"content-type": "application/pdf"})
        ctx.sleep = lambda s: None
        src.collect(ctx)
        assert [d.isoformat() for d in src.missing_dates(ctx)][:2] == ["2026-10-15", "2026-10-14"]


def test_404_page_is_not_ok_and_is_eventually_given_up(short_backfill, fixtures_dir):
    page = (fixtures_dir / "cpcb_bulletin/missing_date.html").read_bytes()
    src = CpcbBulletin()
    ctx = make_ctx(short_backfill)
    ctx.sleep = lambda s: None
    short_backfill.sources["cpcb_bulletin"]["max_per_run"] = 100
    with respx.mock:
        respx.get(URL).respond(200, content=page, headers={"content-type": "text/html"})
        recs = src.collect(ctx)
        assert {r.error for r in recs} == {NOT_PUBLISHED}
        src.collect(ctx)  # second failed attempt
    # 9 dates (10th..18th); those older than 7 days are given up after 2 attempts
    remaining = {d.isoformat() for d in src.missing_dates(ctx)}
    assert remaining == {f"2026-10-{d}" for d in range(11, 19)}


def test_backfill_ignores_the_cap(short_backfill):
    ctx = make_ctx(short_backfill)
    ctx.sleep = lambda s: None
    with respx.mock:
        respx.get(URL).respond(200, content=FAKE_PDF, headers={"content-type": "application/pdf"})
        recs = CpcbBulletin().backfill(ctx)
    assert len(recs) == 9 and CpcbBulletin().missing_dates(ctx) == []


def test_non_pdf_body_is_rejected(short_backfill):
    ctx = make_ctx(short_backfill)
    ctx.sleep = lambda s: None
    with respx.mock:
        respx.get(URL).respond(200, html="<html>maintenance</html>")
        recs = CpcbBulletin().collect(ctx)
    assert {r.error for r in recs} == {"response is not a PDF"}
