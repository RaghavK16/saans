from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import respx

from saans import db, runner
from saans.brief import render, slot_label, write_brief
from saans.brief.build import build_brief
from tests.test_runner import NOW, mock_all

IST = ZoneInfo("Asia/Kolkata")


def _collected(config, fixtures_dir, now=NOW):
    config.sources["cpcb_bulletin"].update(delay_seconds=0, max_per_run=2)
    with respx.mock(assert_all_called=False) as router:
        mock_all(router, fixtures_dir)
        ctx = runner.open_context(config, "run", clock=lambda: now)
        runner.finish(ctx, runner.collect(ctx))
    return ctx


def test_outlook_covers_06_to_23_ist_for_home_and_office(config, fixtures_dir):
    ctx = _collected(config, fixtures_dir)
    b = build_brief(ctx.conn, config, NOW)
    assert [loc.point.key for loc in b.locations] == ["home", "office"]
    home = b.locations[0]
    assert [h.local_time.strftime('%H:%M') for h in home.hours] == [f'{h:02d}:30' for h in range(6, 24)]
    assert all(h.instant.valid for h in home.hours)
    assert any(h.official.valid for h in home.hours)  # past_days=1 gives 24 h of history
    assert home.peak().instant.value == max(h.instant.value for h in home.hours)
    assert not b.same_grid_cell  # fixture: home (28.70, 77.20) vs office (28.60, 77.30)


def test_fires_reported_per_product_and_health_lists_every_source(config, fixtures_dir):
    later = datetime(2026, 10, 18, 2, 0, tzinfo=timezone.utc)  # fixture detections are 17 Oct
    ctx = _collected(config, fixtures_dir, now=later)
    b = build_brief(ctx.conn, config, later)
    assert set(b.fires_24h) == {"VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"}
    assert {h.source: h.status for h in b.health}["datagovin"] == "skipped"
    assert b.observations == {"home": [], "office": []}


def test_nearest_stations_with_key(config_with_keys, fixtures_dir):
    ctx = _collected(config_with_keys, fixtures_dir)
    b = build_brief(ctx.conn, config_with_keys, NOW)
    home = b.observations["home"]
    assert len(home) == 2 and home[0].distance_km <= home[1].distance_km
    assert all(o.aqi is not None for o in home)
    assert b.observations["office"][0].station.endswith("Noida - UPPCB") or "Noida" in b.observations["office"][0].station


def test_gap_note_when_runs_are_days_apart(config, fixtures_dir):
    _collected(config, fixtures_dir, now=NOW - timedelta(days=3))
    ctx = _collected(config, fixtures_dir)
    b = build_brief(ctx.conn, config, NOW)
    assert b.previous_run_gap == timedelta(days=3)
    assert any("can't be recovered" in n for n in b.notes)


def test_empty_database_renders_without_errors(config):
    conn = db.connect(config.db_path)
    b = build_brief(conn, config, NOW)
    out = render(b, IST)
    assert "No forecast stored for this location yet" in out["md"]
    assert "No fire data stored yet" in out["html"]
    assert any("run `saans run`" in n for n in b.notes)


def test_rendered_brief_labels_instant_vs_official_and_credits_sources(config, fixtures_dir):
    ctx = _collected(config, fixtures_dir)
    paths = write_brief(ctx.conn, config, NOW)
    md, html = (p.read_text() for p in paths)
    for text in (md, html):
        assert "Instant" in text and "24 h" in text and "not" in text and "official" in text
        assert "Open-Meteo (CC BY 4.0)" in text
    assert "| 07:30 |" in md and "| 08:30 |" in md
    # fixture day is a Sunday: workout rows are labelled, commute rows are not
    assert "| 07:30 |" in md and "leave home" not in md and "leave office" not in md
    assert md.count("| workout |") == 4  # 07:30, 08:30, 19:30, 20:30 on the home table
    assert "<script" not in html  # static, no JS


def test_slot_labels_overlap_rules():
    routine = {"workout_slots": ["08:00-09:00", "20:00-21:00"],
               "depart_home_window": "09:00-10:30", "depart_office_window": "16:30-18:30"}
    def at(h, m=30, d=19):  # 19 Oct 2026 is a Monday
        return datetime(2026, 10, d, h, m, tzinfo=IST)

    assert slot_label(at(7), routine, "home") == "workout"         # 07:30-08:30 overlaps 08-09
    assert slot_label(at(8), routine, "home") == "workout · leave home"
    assert slot_label(at(10), routine, "home") == ""               # 10:30-11:30 starts as window ends
    assert slot_label(at(9, 0), routine, "home") == "leave home"
    assert slot_label(at(16), routine, "office") == "leave office"
    assert slot_label(at(18), routine, "office") == ""             # window ends 18:30
    assert slot_label(at(16), routine, "home") == ""               # office plans stay off the home table
    assert slot_label(at(8), routine, "office") == ""
    assert slot_label(at(8, d=18), routine, "home") == "workout"     # Sunday: no commute
    assert slot_label(at(16, d=18), routine, "office") == ""


def test_plan_is_built_from_stored_forecasts_and_rendered_first(config, fixtures_dir):
    ctx = _collected(config, fixtures_dir)
    b = build_brief(ctx.conn, config, NOW)  # Sunday 17:26 IST
    lines = b.plan.summary_lines
    assert len(lines) == 5
    assert lines[0].startswith("Air (home), rest of today: instant NAQI")
    assert lines[1].startswith("Workout: ")            # 20-21 slot still ahead
    assert lines[3] == "Commute: none (weekend)"
    assert lines[4].startswith("Office days (next week): ")
    md = render(b, IST)["md"]
    assert md.index("## Today's plan") < md.index("## Today's outlook")
    assert "**Purifier & windows**" in md


def test_no_plan_without_a_forecast(config):
    conn = db.connect(config.db_path)
    b = build_brief(conn, config, NOW)
    assert b.plan is None
    assert "no plan" in render(b, IST)["html"]
