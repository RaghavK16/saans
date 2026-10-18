from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from saans.config import ConfigError, load_config
from tests.conftest import REPO_ROOT


def _write(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())
    mutate(data)
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_repo_config_loads(config):
    assert config.locations["home"].cpcb_city == "Delhi"
    assert config.locations["office"].cpcb_city == "Noida"
    assert len(config.route_points) == 3
    assert config.fire_bbox == (73.8, 27.6, 77.6, 32.6)
    assert config.db_path == config.root / "data" / "saans.db"


def test_committed_config_is_locality_level_only():
    """Public repo rule (D-005): coordinates rounded to 2 decimals, no addresses."""
    data = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())
    points = list(data["locations"].values()) + data["route"]["points"] + data["wind_points"]
    for p in points:
        for coord in (p["lat"], p["lon"]):
            assert round(coord, 2) == coord, p


def test_no_secrets_without_env(config):
    assert config.secrets.get("FIRMS_MAP_KEY") is None
    assert config.secrets.all_values() == []


def test_secrets_from_env_file(config_with_keys):
    assert config_with_keys.secrets.get("FIRMS_MAP_KEY") == "test-firms-key"
    assert set(config_with_keys.secrets.all_values()) == {"test-dgi-key", "test-firms-key"}


def test_environment_overrides_env_file(tmp_path, monkeypatch):
    shutil.copy(REPO_ROOT / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / ".env").write_text("FIRMS_MAP_KEY=from-file\n")
    monkeypatch.setenv("FIRMS_MAP_KEY", "from-env")
    assert load_config(tmp_path / "config.yaml").secrets.get("FIRMS_MAP_KEY") == "from-env"


def test_unknown_env_vars_are_ignored(tmp_path, monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    shutil.copy(REPO_ROOT / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / ".env").write_text("SOMETHING_ELSE=x\n")
    assert load_config(tmp_path / "config.yaml").secrets.values == {}


def test_missing_office_is_an_error(tmp_path):
    p = _write(tmp_path, lambda d: d["locations"].pop("office"))
    with pytest.raises(ConfigError, match="office"):
        load_config(p)


def test_bad_bbox_is_an_error(tmp_path):
    p = _write(tmp_path, lambda d: d["fire_region"].update(bbox=[77.6, 27.6, 73.8, 32.6]))
    with pytest.raises(ConfigError, match="bbox"):
        load_config(p)


def test_out_of_range_coordinates_are_an_error(tmp_path):
    p = _write(tmp_path, lambda d: d["locations"]["home"].update(lat=128.7))
    with pytest.raises(ConfigError, match="home"):
        load_config(p)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")
