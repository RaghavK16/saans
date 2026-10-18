from __future__ import annotations

import json

import pytest
import respx

from saans.sources.base import SourceSkipped
from saans.sources.datagovin import URL, DataGovIn


def test_skipped_without_key(ctx):
    with pytest.raises(SourceSkipped, match="DATAGOVIN_API_KEY"):
        DataGovIn().collect(ctx)


def test_collects_each_city_and_redacts_key(ctx_with_keys, fixtures_dir):
    pages = {c: (fixtures_dir / f"datagovin/{c.lower()}_page.json").read_bytes() for c in ("Delhi", "Noida")}
    ctx_with_keys.config.sources["datagovin"]["page_size"] = 10
    with respx.mock:
        def reply(request):
            import httpx
            city = request.url.params["filters[city]"]
            offset = int(request.url.params["offset"])
            body = json.loads(pages[city])
            if offset:  # second page: pretend the rest is empty
                body["records"] = []
            return httpx.Response(200, json=body)
        route = respx.get(URL).mock(side_effect=reply)
        recs = DataGovIn().collect(ctx_with_keys)
    cities = [c.request.url.params["filters[city]"] for c in route.calls]
    assert cities[0] == "Delhi" and "Noida" in cities
    assert all(c.request.url.params["api-key"] == "test-dgi-key" for c in route.calls)
    assert all("test-dgi-key" not in r.url for r in recs)


def test_parse_converts_ist_to_utc(ctx_with_keys, fixtures_dir):
    body = (fixtures_dir / "datagovin/delhi_page.json").read_bytes()
    raw = ctx_with_keys.store.save(source="datagovin", url="u", fetched_at=ctx_with_keys.now,
                                   body=body, status_code=200, content_type="application/json", ok=True)
    rows = DataGovIn().parse(raw, body)
    assert len(rows) == 10
    narela = next(r for r in rows if r["station"].startswith("Narela") and r["pollutant"] == "PM2.5")
    assert narela["observed_at"] == "2026-10-17T18:30:00Z"  # 18-10-2026 00:00 IST
    assert narela["avg_value"] == 226.0 and narela["city"] == "Delhi"


def test_bad_key_is_recorded_as_failure(ctx_with_keys):
    with respx.mock:
        respx.get(URL).respond(403, json={"error": "Key not authorised"})
        recs = DataGovIn().collect(ctx_with_keys)
    assert len(recs) == 2 and not any(r.ok for r in recs)  # one attempt per city, then stop


def test_na_values_become_null(ctx_with_keys):
    body = json.dumps({"records": [{"station": "S", "pollutant_id": "CO", "last_update": "18-10-2026 05:00:00",
                                    "avg_value": "NA", "min_value": "", "max_value": "12", "latitude": "x"}]}).encode()
    raw = ctx_with_keys.store.save(source="datagovin", url="u", fetched_at=ctx_with_keys.now,
                                   body=body, status_code=200, content_type="application/json", ok=True)
    (row,) = DataGovIn().parse(raw, body)
    assert (row["avg_value"], row["min_value"], row["max_value"], row["lat"]) == (None, None, 12.0, None)
