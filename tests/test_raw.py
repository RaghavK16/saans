from __future__ import annotations

import gzip
from datetime import datetime, timezone

import httpx
import pytest
import respx

from saans import db
from saans.raw import Fetcher, RawStore, redact

NOW = datetime(2026, 10, 18, 1, 30, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    conn = db.connect(tmp_path / "saans.db")
    return RawStore(conn, tmp_path / "raw", secrets=["sekret-key-123"])


@pytest.fixture
def fetcher(store):
    client = httpx.Client()
    yield Fetcher(client, store, clock=lambda: NOW)
    client.close()


def test_redact_replaces_every_secret():
    assert redact("a?k=s1&t=s22", ["s1", "s22"]) == "a?k=REDACTED&t=REDACTED"
    assert redact("nothing", []) == "nothing"


def test_save_writes_gzipped_body_and_index_row(store, tmp_path):
    rec = store.save(
        source="demo",
        url="https://x.test/a?api-key=sekret-key-123",
        fetched_at=NOW,
        body=b'{"a": 1}',
        status_code=200,
        content_type="application/json; charset=utf-8",
        ok=True,
        request_key="2026-10-18",
        params={"locations": ["home"]},
    )
    assert rec.ok and rec.content_type == "application/json"
    assert "sekret" not in rec.url and "REDACTED" in rec.url
    assert rec.path.startswith("demo/2026-10-18/013000Z_2026-10-18_") and rec.path.endswith(".json.gz")
    assert gzip.decompress((tmp_path / "raw" / rec.path).read_bytes()) == b'{"a": 1}'
    assert store.read_body(rec) == b'{"a": 1}'
    assert rec.params == {"locations": ["home"]}
    assert store.ok_request_keys("demo") == {"2026-10-18"}
    assert store.last_ok_fetch("demo") == "2026-10-18T01:30:00Z"


def test_failed_responses_are_indexed_but_not_ok(store):
    store.save(source="demo", url="u", fetched_at=NOW, body=None, status_code=None,
               content_type=None, ok=False, error="timeout using sekret-key-123")
    assert list(store.iter_ok("demo")) == []
    row = store.conn.execute("SELECT error FROM raw_responses").fetchone()
    assert row[0] == "timeout using REDACTED"


@respx.mock
def test_fetcher_stores_success(fetcher, store):
    respx.get("https://api.test/data").respond(200, json={"ok": True})
    rec = fetcher.get("demo", "https://api.test/data", query={"key": "sekret-key-123", "q": "1"})
    assert rec.ok and rec.status_code == 200
    assert rec.url == "https://api.test/data?key=REDACTED&q=1"
    assert store.read_body(rec) == b'{"ok":true}'


@respx.mock
def test_fetcher_stores_http_errors_with_body(fetcher, store):
    respx.get("https://api.test/data").respond(401, text="Invalid MAP_KEY.")
    rec = fetcher.get("demo", "https://api.test/data")
    assert not rec.ok and rec.error == "HTTP 401"
    assert store.read_body(rec) == b"Invalid MAP_KEY."


@respx.mock
def test_fetcher_records_transport_errors(fetcher, store):
    respx.get("https://api.test/sekret-key-123/data").mock(side_effect=httpx.ConnectTimeout("slow"))
    rec = fetcher.get("demo", "https://api.test/sekret-key-123/data")
    assert not rec.ok and rec.path is None and "ConnectTimeout" in rec.error
    assert "sekret" not in rec.url


@respx.mock
def test_custom_validator_marks_bad_payload(fetcher):
    respx.get("https://api.test/pdf").respond(200, html="<script>404</script>")
    rec = fetcher.get(
        "demo", "https://api.test/pdf",
        validate=lambda r: None if r.content.startswith(b"%PDF") else "not a PDF",
    )
    assert not rec.ok and rec.error == "not a PDF"
