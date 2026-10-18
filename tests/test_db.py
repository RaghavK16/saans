from saans import db


def test_connect_applies_migrations_once(tmp_path):
    path = tmp_path / "data" / "saans.db"
    conn = db.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"runs", "source_runs", "raw_responses", *db.PARSED_TABLES} <= tables
    assert db.migrate(conn) == []  # idempotent
    conn.close()
    assert db.migrate(db.connect(path)) == []


def test_foreign_keys_enforced(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    import sqlite3

    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO source_runs (run_id, source, status, started_at) VALUES (999, 's', 'ok', 't')"
        )
