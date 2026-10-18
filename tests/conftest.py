from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from saans.config import Config, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    """The real config.yaml, copied into tmp_path so data/ and out/ land there. No secrets."""
    for name in ("DATAGOVIN_API_KEY", "FIRMS_MAP_KEY", "OPENAQ_API_KEY", "WAQI_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    shutil.copy(REPO_ROOT / "config.yaml", tmp_path / "config.yaml")
    return load_config(tmp_path / "config.yaml")


@pytest.fixture
def config_with_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    for name in ("DATAGOVIN_API_KEY", "FIRMS_MAP_KEY", "OPENAQ_API_KEY", "WAQI_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    shutil.copy(REPO_ROOT / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / ".env").write_text("DATAGOVIN_API_KEY=test-dgi-key\nFIRMS_MAP_KEY=test-firms-key\n")
    return load_config(tmp_path / "config.yaml")


NOW = datetime(2026, 10, 18, 11, 56, tzinfo=timezone.utc)


def make_ctx(cfg: Config, now=NOW):
    import httpx

    from saans import db
    from saans.raw import Fetcher, RawStore
    from saans.sources.base import RunContext

    conn = db.connect(cfg.db_path)
    store = RawStore(conn, cfg.raw_dir, cfg.secrets.all_values())
    client = httpx.Client(timeout=cfg.http_timeout, headers={"User-Agent": cfg.user_agent})
    run_id = conn.execute(
        "INSERT INTO runs (command, started_at) VALUES ('test', ?)", (now.isoformat(),)
    ).lastrowid
    return RunContext(cfg, conn, store, Fetcher(client, store, clock=lambda: now), now, run_id)


@pytest.fixture
def ctx(config):
    return make_ctx(config)


@pytest.fixture
def ctx_with_keys(config_with_keys):
    return make_ctx(config_with_keys)
