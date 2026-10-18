"""NASA FIRMS VIIRS fire hotspots over the stubble belt. DATA_SOURCES.md §5, DECISIONS.md D-013.

Two modes, same CSV format:
- No key: NASA's public South Asia files (last 48 h, or 7 d after a longer gap). Parse filters
  them to the configured bbox.
- FIRMS_MAP_KEY set: the area API for the exact bbox, re-fetching from the last successful day
  (DAY_RANGE is capped at 5, so longer catch-ups are chunked).
Overlapping windows are fine: fire_hotspots de-duplicates on (product, lat, lon, acquired_at).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

import httpx

from saans.raw import RawRecord
from saans.sources.base import Row, RunContext, Source

AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{product}/{bbox}/{days}/{start}"
PUBLIC_URL = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/{folder}/csv/{prefix}_VIIRS_C2_South_Asia_{window}.csv"
PUBLIC_FILES = {  # product -> (folder, file prefix)
    "VIIRS_SNPP_NRT": ("suomi-npp-viirs-c2", "SUOMI"),
    "VIIRS_NOAA20_NRT": ("noaa-20-viirs-c2", "J1"),
    "VIIRS_NOAA21_NRT": ("noaa-21-viirs-c2", "J2"),
}
MAX_DAY_RANGE = 5
SHORT_WINDOW_MAX_GAP = timedelta(hours=40)  # 48 h file still overlaps the previous fetch


def validate_csv(resp: httpx.Response) -> str | None:
    if resp.status_code != 200:
        return f"HTTP {resp.status_code}"
    if not resp.content.startswith(b"latitude,longitude"):
        return "response is not FIRMS CSV: " + resp.content[:80].decode(errors="replace")
    return None


def _acquired_at(acq_date: str, acq_time: str) -> str:
    hhmm = acq_time.strip().zfill(4)
    return f"{acq_date}T{hhmm[:2]}:{hhmm[2:]}:00Z"


def _float(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


class Firms(Source):
    name = "firms"
    table = "fire_hotspots"

    def _products(self, ctx: RunContext) -> list[str]:
        return list(ctx.config.source_settings(self.name).get("products", PUBLIC_FILES))

    def _last_ok(self, ctx: RunContext, product: str) -> datetime | None:
        row = ctx.conn.execute(
            "SELECT MAX(fetched_at) FROM raw_responses WHERE source = ? AND ok = 1 "
            "AND json_extract(params_json, '$.product') = ?", (self.name, product)).fetchone()
        return datetime.fromisoformat(row[0].replace("Z", "+00:00")) if row[0] else None

    def collect(self, ctx: RunContext) -> list[RawRecord]:
        key = ctx.config.secrets.get("FIRMS_MAP_KEY")
        bbox = list(ctx.config.fire_bbox)
        records = []
        for product in self._products(ctx):
            last = self._last_ok(ctx, product)
            if key:
                records += self._collect_area(ctx, key, product, bbox, last)
            else:
                records.append(self._collect_public(ctx, product, bbox, last))
        return records

    def _collect_public(self, ctx, product, bbox, last) -> RawRecord:
        folder, prefix = PUBLIC_FILES[product]
        window = "48h" if last and ctx.now - last <= SHORT_WINDOW_MAX_GAP else "7d"
        url = PUBLIC_URL.format(folder=folder, prefix=prefix, window=window)
        return ctx.fetcher.get(
            self.name, url, run_id=ctx.run_id, validate=validate_csv,
            request_key=f"{product}:public:{window}",
            params={"product": product, "bbox": bbox, "mode": "public", "window": window},
        )

    def _collect_area(self, ctx, key, product, bbox, last) -> list[RawRecord]:
        today = ctx.now.date()
        max_days = int(ctx.config.source_settings(self.name).get("max_catchup_days", 10))
        earliest = today - timedelta(days=max_days - 1)
        start = max(last.date() if last else today - timedelta(days=1), earliest)
        out = []
        while start <= today:
            days = min(MAX_DAY_RANGE, (today - start).days + 1)
            url = AREA_URL.format(key=key, product=product, bbox=",".join(map(str, bbox)),
                                  days=days, start=start.isoformat())
            out.append(ctx.fetcher.get(
                self.name, url, run_id=ctx.run_id, validate=validate_csv,
                request_key=f"{product}:{start.isoformat()}:{days}",
                params={"product": product, "bbox": bbox, "mode": "area",
                        "start": start.isoformat(), "days": days},
            ))
            start += timedelta(days=days)
        return out

    def parse(self, raw: RawRecord, body: bytes) -> list[Row]:
        west, south, east, north = raw.params["bbox"]
        rows = []
        for r in csv.DictReader(io.StringIO(body.decode())):
            lat, lon = _float(r.get("latitude")), _float(r.get("longitude"))
            if lat is None or lon is None or not (south <= lat <= north and west <= lon <= east):
                continue
            rows.append({
                "product": raw.params["product"],
                "lat": lat,
                "lon": lon,
                "acquired_at": _acquired_at(r["acq_date"], r["acq_time"]),
                "raw_id": raw.id,
                "satellite": r.get("satellite"),
                "confidence": r.get("confidence"),
                "frp_mw": _float(r.get("frp")),
                "bright_ti4_k": _float(r.get("bright_ti4") or r.get("brightness")),
                "daynight": r.get("daynight"),
            })
        return rows

