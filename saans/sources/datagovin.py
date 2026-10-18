"""CPCB station snapshot via data.gov.in. Needs DATAGOVIN_API_KEY. DATA_SOURCES.md §3.

Latest snapshot only (no history), so a day without a run is a day lost from this source.
Values appear to be sub-indices, not concentrations; they are stored as-is.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from saans.raw import RawRecord
from saans.sources.base import Row, RunContext, Source, SourceSkipped, json_ok

log = logging.getLogger(__name__)

URL = "https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"
IST = ZoneInfo("Asia/Kolkata")
MAX_PAGES_PER_CITY = 10  # safety valve; Delhi is ~406 rows, one page at limit=1000


def _num(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "", "NA") else None
    except ValueError:
        return None


def _observed_at(last_update: str) -> str:
    # "18-10-2026 00:00:00" in IST -> UTC ISO
    local = datetime.strptime(last_update, "%d-%m-%Y %H:%M:%S").replace(tzinfo=IST)
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DataGovIn(Source):
    name = "datagovin"
    table = "station_readings"

    def collect(self, ctx: RunContext) -> list[RawRecord]:
        key = ctx.config.secrets.get("DATAGOVIN_API_KEY")
        if not key:
            raise SourceSkipped("DATAGOVIN_API_KEY not set (DATA_SOURCES.md §3)")
        settings = ctx.config.source_settings(self.name)
        page_size = int(settings.get("page_size", 1000))
        records: list[RawRecord] = []
        for city in settings.get("cities", ["Delhi"]):
            offset = 0
            for _ in range(MAX_PAGES_PER_CITY):
                rec = ctx.fetcher.get(
                    self.name, URL, run_id=ctx.run_id, validate=json_ok,
                    query={"api-key": key, "format": "json", "limit": page_size,
                           "offset": offset, "filters[city]": city},
                    params={"city": city, "offset": offset},
                )
                records.append(rec)
                if not rec.ok:
                    break
                page = json.loads(ctx.store.read_body(rec))
                got = len(page.get("records", []))
                offset += got
                if got == 0 or offset >= int(page.get("total", 0)):
                    break
        return records

    def parse(self, raw: RawRecord, body: bytes) -> list[Row]:
        rows = []
        for r in json.loads(body).get("records", []):
            if not r.get("station") or not r.get("pollutant_id") or not r.get("last_update"):
                continue
            rows.append({
                "raw_id": raw.id,
                "source": "cpcb/data.gov.in",
                "station": r["station"],
                "city": r.get("city"),
                "state": r.get("state"),
                "lat": _num(r.get("latitude")),
                "lon": _num(r.get("longitude")),
                "pollutant": r["pollutant_id"],
                "observed_at": _observed_at(r["last_update"]),
                "min_value": _num(r.get("min_value")),
                "max_value": _num(r.get("max_value")),
                "avg_value": _num(r.get("avg_value")),
            })
        return rows
