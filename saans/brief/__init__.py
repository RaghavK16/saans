"""Daily brief: gather facts (build.py) and render Markdown + HTML (templates/)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from saans import naqi
from saans.brief.build import Brief, build_brief
from saans.config import Config


TOPIC_TITLES = {
    "workout": "Workout",
    "home_air": "Purifier & windows",
    "commute": "Commute",
    "office_days": "Office days",
}


def _in_window(t: datetime, window: str) -> bool:
    start, end = window.split("-")
    minutes = t.hour * 60 + t.minute
    s = int(start[:2]) * 60 + int(start[3:])
    e = int(end[:2]) * 60 + int(end[3:])
    return s < minutes + 60 and e > minutes  # the hour row [t, t+60) overlaps the window


def slot_label(t: datetime, routine: dict, location_key: str) -> str:
    """Which of your plans fall in this hour, for the table of `location_key`."""
    labels = []
    weekday = t.weekday() < 5  # commute labels on office days (Mon–Fri) only
    if location_key == "home":
        if any(_in_window(t, w) for w in routine.get("workout_slots", [])):
            labels.append("workout")
        if weekday and routine.get("depart_home_window") and _in_window(t, routine["depart_home_window"]):
            labels.append("leave home")
    if location_key == "office" and weekday:
        if routine.get("depart_office_window") and _in_window(t, routine["depart_office_window"]):
            labels.append("leave office")
    return " · ".join(labels)


def human_gap(gap: timedelta) -> str:
    hours = gap.total_seconds() / 3600
    return f"{hours:.0f} h" if hours < 48 else f"{hours / 24:.1f} days"


def _environment(tz: ZoneInfo) -> Environment:
    env = Environment(
        loader=PackageLoader("saans", "brief/templates"),
        autoescape=select_autoescape(["html.j2"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters.update(
        slot_label=slot_label,
        human_gap=human_gap,
        local_time=lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
        .astimezone(tz).strftime("%d %b %H:%M"),
        cat_class=lambda c: "c-" + (c or "none").lower().replace(" ", "-"),
        category_of=lambda v: naqi.category(v) if v is not None else None,
        topic_title=lambda topic: TOPIC_TITLES.get(topic, topic),
    )
    return env


def render(brief: Brief, tz: ZoneInfo) -> dict[str, str]:
    env = _environment(tz)
    return {ext: env.get_template(f"brief.{ext}.j2").render(b=brief) for ext in ("md", "html")}


def write_brief(conn: sqlite3.Connection, config: Config, now: datetime) -> list[Path]:
    tz = ZoneInfo(config.timezone)
    brief = build_brief(conn, config, now)
    config.out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext, text in render(brief, tz).items():
        path = config.out_dir / f"brief-{brief.day.isoformat()}.{ext}"
        path.write_text(text)
        paths.append(path)
    return paths
