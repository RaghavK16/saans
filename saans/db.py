"""SQLite connection + forward-only migrations from saans/migrations/NNN_name.sql."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

PARSED_TABLES = (
    "aq_forecast_hourly",
    "weather_forecast_hourly",
    "station_readings",
    "fire_hotspots",
)


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def _migration_files() -> list[tuple[str, str]]:
    folder = resources.files("saans") / "migrations"
    files = sorted(f for f in folder.iterdir() if f.name.endswith(".sql"))
    return [(f.name, f.read_text()) for f in files]


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply pending migrations in filename order. Returns the names applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for name, sql in _migration_files():
        if name in done:
            continue
        # executescript() commits any open transaction first, so wrap the migration and its
        # bookkeeping row in one explicit transaction: a failing migration leaves no trace.
        safe_name = name.replace("'", "''")
        try:
            conn.executescript(
                f"BEGIN;\n{sql}\n;INSERT INTO schema_migrations VALUES "
                f"('{safe_name}', strftime('%Y-%m-%dT%H:%M:%SZ','now'));\nCOMMIT;"
            )
        except sqlite3.Error:
            conn.rollback()
            raise
        applied.append(name)
    return applied
