"""Orchestrates runs: collect every source, log outcomes, write the brief, reparse, backfill.

A source that is skipped (missing key) or fails never stops the others (CLAUDE.md).
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from saans import db
from saans.config import Config
from saans.raw import Fetcher, RawStore, utc_iso
from saans.sources.base import RunContext, Source, SourceSkipped
from saans.sources.cpcb_bulletin import CpcbBulletin
from saans.sources.datagovin import DataGovIn
from saans.sources.firms import Firms
from saans.sources.open_meteo import OpenMeteoAirQuality, OpenMeteoWeather

log = logging.getLogger(__name__)

# Order = how irreplaceable the data is (ROADMAP Phase 1): forecasts and snapshots first.
SOURCES: list[Source] = [
    OpenMeteoAirQuality(),
    OpenMeteoWeather(),
    DataGovIn(),
    Firms(),
    CpcbBulletin(),
]


def source_by_name(name: str) -> Source:
    for s in SOURCES:
        if s.name == name:
            return s
    raise KeyError(f"unknown source {name!r}; known: {', '.join(s.name for s in SOURCES)}")


@dataclass
class SourceOutcome:
    source: str
    status: str  # ok | skipped | failed
    detail: str = ""
    raw_count: int = 0
    row_count: int = 0


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def open_context(
    config: Config,
    command: str,
    *,
    client: httpx.Client | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> RunContext:
    conn = db.connect(config.db_path)
    store = RawStore(conn, config.raw_dir, config.secrets.all_values())
    client = client or httpx.Client(
        timeout=config.http_timeout,
        headers={"User-Agent": config.user_agent},
        follow_redirects=True,
        transport=httpx.HTTPTransport(retries=2),
    )
    now = clock()
    run_id = conn.execute(
        "INSERT INTO runs (command, started_at) VALUES (?, ?)", (command, utc_iso(now))
    ).lastrowid
    conn.commit()
    return RunContext(config, conn, store, Fetcher(client, store, clock=clock), now, run_id)


def _parse_and_insert(ctx: RunContext, source: Source, records) -> tuple[int, list[str]]:
    rows_total, errors = 0, []
    for rec in records:
        if not rec.ok or source.table is None:
            continue
        try:
            rows_total += source.insert(ctx.conn, source.parse(rec, ctx.store.read_body(rec)))
        except Exception as e:  # raw is kept; `saans reparse` can retry after a fix
            log.exception("%s: parse failed for raw %s", source.name, rec.id)
            errors.append(f"parse error on raw {rec.id}: {e}")
    return rows_total, errors


def _record(ctx: RunContext, outcome: SourceOutcome, started: datetime) -> None:
    ctx.conn.execute(
        "INSERT INTO source_runs (run_id, source, status, detail, raw_count, row_count, "
        "started_at, finished_at) VALUES (?,?,?,?,?,?,?,?)",
        (ctx.run_id, outcome.source, outcome.status, outcome.detail, outcome.raw_count,
         outcome.row_count, utc_iso(started), utc_iso(utcnow())),
    )
    ctx.conn.commit()


def run_source(ctx: RunContext, source: Source, action: str = "collect") -> SourceOutcome:
    started = utcnow()
    try:
        records = getattr(source, action)(ctx)
    except SourceSkipped as e:
        outcome = SourceOutcome(source.name, "skipped", str(e))
        log.warning("%s: skipped: %s", source.name, e)
    except Exception as e:
        log.exception("%s: %s crashed", source.name, action)
        outcome = SourceOutcome(source.name, "failed", f"{type(e).__name__}: {e}")
    else:
        ok = [r for r in records if r.ok]
        rows, parse_errors = _parse_and_insert(ctx, source, records)
        failed = [r for r in records if not r.ok]
        problems = [f"{r.request_key or 'request'}: {r.error}" for r in failed] + parse_errors
        status = "failed" if (records and not ok) or parse_errors else "ok"
        detail = f"{len(ok)}/{len(records)} responses ok" if records else "nothing to fetch"
        if problems:
            detail += "; " + "; ".join(problems[:3]) + (" …" if len(problems) > 3 else "")
        outcome = SourceOutcome(source.name, status, detail, len(records), rows)
        log.info("%s: %s (%s rows)", source.name, detail, rows)
    _record(ctx, outcome, started)
    return outcome


def finish(ctx: RunContext, outcomes: list[SourceOutcome]) -> str:
    attempted = [o for o in outcomes if o.status != "skipped"]
    failed = [o for o in attempted if o.status == "failed"]
    status = "failed" if attempted and len(failed) == len(attempted) else ("partial" if failed else "ok")
    ctx.conn.execute("UPDATE runs SET finished_at = ?, status = ? WHERE id = ?",
                     (utc_iso(utcnow()), status, ctx.run_id))
    ctx.conn.commit()
    return status


def collect(ctx: RunContext) -> list[SourceOutcome]:
    return [run_source(ctx, s) for s in SOURCES]


def reparse(conn: sqlite3.Connection, store: RawStore) -> dict[str, int]:
    """Rebuild every parsed table from the raw archive."""
    counts: dict[str, int] = {}
    for source in SOURCES:
        if source.table is None:
            continue
        conn.execute(f"DELETE FROM {source.table}")
        conn.commit()
        n = 0
        for rec in store.iter_ok(source.name):
            n += source.insert(conn, source.parse(rec, store.read_body(rec)))
        counts[source.table] = n
    return counts


def dispatch(command: str, config: Config, args: argparse.Namespace) -> int:
    from saans.brief import write_brief  # late import keeps collectors independent of rendering

    if command == "reparse":
        conn = db.connect(config.db_path)
        counts = reparse(conn, RawStore(conn, config.raw_dir, config.secrets.all_values()))
        for table, n in counts.items():
            print(f"{table}: {n} rows")
        return 0

    if command == "brief":
        conn = db.connect(config.db_path)
        paths = write_brief(conn, config, utcnow())
        print("\n".join(str(p) for p in paths))
        return 0

    ctx = open_context(config, command if command != "backfill" else f"backfill {args.source}")
    if command == "backfill":
        try:
            outcomes = [run_source(ctx, source_by_name(args.source), action="backfill")]
        except KeyError as e:
            print(e.args[0])
            return 2
    else:
        outcomes = collect(ctx)
    status = finish(ctx, outcomes)

    for o in outcomes:
        print(f"  {o.status:<8} {o.source:<20} {o.detail}")
    print(f"run {ctx.run_id}: {status}")
    if command == "run":
        for p in write_brief(ctx.conn, config, ctx.now):
            print(f"brief: {p}")
    return 1 if status == "failed" else 0
