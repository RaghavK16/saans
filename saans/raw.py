"""Fetch → store raw → index row. Raw files are immutable (DECISIONS.md D-004)."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

_EXTENSIONS = {
    "application/json": "json",
    "text/csv": "csv",
    "application/pdf": "pdf",
    "text/html": "html",
    "text/plain": "txt",
}

# A validator inspects a response and returns an error message, or None if it is usable.
Validator = Callable[[httpx.Response], str | None]


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def redact(text: str, secrets: list[str]) -> str:
    for s in sorted(secrets, key=len, reverse=True):
        if s:
            text = text.replace(s, "REDACTED")
    return text


def status_200(resp: httpx.Response) -> str | None:
    return None if resp.status_code == 200 else f"HTTP {resp.status_code}"


@dataclass(frozen=True)
class RawRecord:
    id: int
    source: str
    request_key: str | None
    url: str
    params: dict[str, Any]
    fetched_at: str
    status_code: int | None
    content_type: str | None
    path: str | None
    ok: bool
    error: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> RawRecord:
        return cls(
            id=row["id"],
            source=row["source"],
            request_key=row["request_key"],
            url=row["url"],
            params=json.loads(row["params_json"]),
            fetched_at=row["fetched_at"],
            status_code=row["status_code"],
            content_type=row["content_type"],
            path=row["path"],
            ok=bool(row["ok"]),
            error=row["error"],
        )


class RawStore:
    def __init__(self, conn: sqlite3.Connection, raw_dir: Path, secrets: list[str]):
        self.conn = conn
        self.raw_dir = raw_dir
        self.secrets = secrets

    def save(
        self,
        *,
        source: str,
        url: str,
        fetched_at: datetime,
        body: bytes | None,
        status_code: int | None,
        content_type: str | None,
        ok: bool,
        run_id: int | None = None,
        request_key: str | None = None,
        params: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> RawRecord:
        ctype = (content_type or "").split(";")[0].strip().lower() or None
        rel_path = sha = None
        size = None
        if body is not None:
            sha = hashlib.sha256(body).hexdigest()
            size = len(body)
            ext = _EXTENSIONS.get(ctype or "", "bin")
            stamp = fetched_at.astimezone(timezone.utc)
            key_part = f"_{_slug(request_key)}" if request_key else ""
            rel = Path(source) / stamp.strftime("%Y-%m-%d") / (
                f"{stamp.strftime('%H%M%S')}Z{key_part}_{sha[:10]}.{ext}.gz"
            )
            dest = self.raw_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():  # identical content at the same second is the same file
                # mtime=0 keeps the gzip bytes deterministic for identical content.
                dest.write_bytes(gzip.compress(body, mtime=0))
            rel_path = rel.as_posix()
        cur = self.conn.execute(
            """INSERT INTO raw_responses
               (run_id, source, request_key, url, params_json, fetched_at, status_code,
                content_type, sha256, bytes, path, ok, error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                source,
                request_key,
                redact(url, self.secrets),
                json.dumps(params or {}, sort_keys=True),
                utc_iso(fetched_at),
                status_code,
                ctype,
                sha,
                size,
                rel_path,
                int(ok),
                redact(error, self.secrets) if error else None,
            ),
        )
        self.conn.commit()
        return self.get(cur.lastrowid)

    def get(self, raw_id: int) -> RawRecord:
        row = self.conn.execute("SELECT * FROM raw_responses WHERE id = ?", (raw_id,)).fetchone()
        if row is None:
            raise KeyError(raw_id)
        return RawRecord.from_row(row)

    def read_body(self, rec: RawRecord) -> bytes:
        if rec.path is None:
            raise ValueError(f"raw response {rec.id} has no body")
        return gzip.decompress((self.raw_dir / rec.path).read_bytes())

    def iter_ok(self, source: str) -> Iterator[RawRecord]:
        rows = self.conn.execute(
            "SELECT * FROM raw_responses WHERE source = ? AND ok = 1 ORDER BY fetched_at, id",
            (source,),
        ).fetchall()
        for row in rows:
            yield RawRecord.from_row(row)

    def ok_request_keys(self, source: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT request_key FROM raw_responses "
            "WHERE source = ? AND ok = 1 AND request_key IS NOT NULL",
            (source,),
        )
        return {r[0] for r in rows}

    def last_ok_fetch(self, source: str) -> str | None:
        row = self.conn.execute(
            "SELECT MAX(fetched_at) FROM raw_responses WHERE source = ? AND ok = 1", (source,)
        ).fetchone()
        return row[0]


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in text)[:60]


class Fetcher:
    """Performs an HTTP GET and always records the outcome in the raw store, even failures."""

    def __init__(self, client: httpx.Client, store: RawStore, clock: Callable[[], datetime]):
        self.client = client
        self.store = store
        self.clock = clock

    def get(
        self,
        source: str,
        url: str,
        *,
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        run_id: int | None = None,
        request_key: str | None = None,
        params: dict[str, Any] | None = None,
        validate: Validator = status_200,
    ) -> RawRecord:
        fetched_at = self.clock()
        try:
            resp = self.client.get(url, params=query, headers=headers)
        except httpx.HTTPError as e:
            full_url = str(httpx.URL(url, params=query)) if query else url
            log.warning("%s: request failed: %s", source, redact(str(e), self.store.secrets))
            return self.store.save(
                source=source,
                url=full_url,
                fetched_at=fetched_at,
                body=None,
                status_code=None,
                content_type=None,
                ok=False,
                run_id=run_id,
                request_key=request_key,
                params=params,
                error=f"{type(e).__name__}: {e}",
            )
        error = validate(resp)
        return self.store.save(
            source=source,
            url=str(resp.request.url),
            fetched_at=fetched_at,
            body=resp.content,
            status_code=resp.status_code,
            content_type=resp.headers.get("content-type"),
            ok=error is None,
            run_id=run_id,
            request_key=request_key,
            params=params,
            error=error,
        )
