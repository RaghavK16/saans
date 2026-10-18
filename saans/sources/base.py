"""The contract every data source implements (CLAUDE.md: one source = one module)."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

import httpx

from saans.config import Config
from saans.raw import Fetcher, RawRecord, RawStore


class SourceSkipped(Exception):
    """Raised by collect() when a source can't run (e.g. missing key). Not a failure."""


@dataclass
class RunContext:
    config: Config
    conn: sqlite3.Connection
    store: RawStore
    fetcher: Fetcher
    now: datetime  # UTC, fixed for the whole run
    run_id: int | None = None
    sleep: Callable[[float], None] = field(default=time.sleep)  # injectable for tests


Row = dict[str, Any]


class Source:
    name: ClassVar[str]
    table: ClassVar[str | None] = None  # parsed table; None = raw-only for now

    def collect(self, ctx: RunContext) -> list[RawRecord]:
        raise NotImplementedError

    def parse(self, raw: RawRecord, body: bytes) -> list[Row]:
        """Pure: raw response -> rows for `table`. Must be deterministic (used by reparse)."""
        return []

    def backfill(self, ctx: RunContext) -> list[RawRecord]:
        raise SourceSkipped(f"{self.name} has no backfill")

    # -- helpers ---------------------------------------------------------------

    def insert(self, conn: sqlite3.Connection, rows: list[Row]) -> int:
        if not rows or self.table is None:
            return 0
        cols = list(rows[0])
        sql = (
            f"INSERT OR IGNORE INTO {self.table} ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)})"
        )
        before = conn.total_changes
        conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
        conn.commit()
        return conn.total_changes - before


def json_ok(resp: httpx.Response) -> str | None:
    """Validator: HTTP 200 and a JSON body that isn't an API error object."""
    if resp.status_code != 200:
        return f"HTTP {resp.status_code}"
    try:
        data = json.loads(resp.content)
    except ValueError:
        return "body is not JSON"
    if isinstance(data, dict) and data.get("error"):
        return f"API error: {data.get('reason') or data.get('error')}"
    return None
