"""CPCB daily AQI bulletin PDFs: official city AQI at 4 PM IST. No key. DATA_SOURCES.md §4.

Raw-only in Phase 1; parsing the PDF tables lands with the scorecard (Phase 4).
The URL scheme is observed, not documented: displaypdf.php?id=base64("Downloads/AQI_Bulletin_YYYYMMDD.pdf").
A date with no bulletin returns HTTP 200 with a JavaScript redirect to /404.php.
"""

from __future__ import annotations

import base64
import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx

from saans.raw import RawRecord
from saans.sources.base import RunContext, Source

log = logging.getLogger(__name__)

URL = "https://cpcb.gov.in/displaypdf.php"
IST = ZoneInfo("Asia/Kolkata")
PUBLISHED_AFTER = time(16, 30)  # bulletin is the 4 PM value; give CPCB a little slack
NOT_PUBLISHED = "not published (CPCB returned its 404 page)"
GIVE_UP_AFTER_DAYS = 7  # a date still missing a week later is assumed never to appear
GIVE_UP_AFTER_ATTEMPTS = 2


def bulletin_id(d: date) -> str:
    return base64.b64encode(f"Downloads/AQI_Bulletin_{d:%Y%m%d}.pdf".encode()).decode()


def validate_pdf(resp: httpx.Response) -> str | None:
    if resp.status_code != 200:
        return f"HTTP {resp.status_code}"
    if resp.content.startswith(b"%PDF"):
        return None
    if b"404.php" in resp.content:
        return NOT_PUBLISHED
    return "response is not a PDF"


def latest_expected(now_utc: datetime) -> date:
    now_ist = now_utc.astimezone(IST)
    return now_ist.date() if now_ist.time() >= PUBLISHED_AFTER else now_ist.date() - timedelta(days=1)


class CpcbBulletin(Source):
    name = "cpcb_bulletin"
    table = None

    def missing_dates(self, ctx: RunContext) -> list[date]:
        """Dates we still want, newest first."""
        start = date.fromisoformat(ctx.config.source_settings(self.name).get("backfill_start", "2025-10-01"))
        end = latest_expected(ctx.now)
        have = ctx.store.ok_request_keys(self.name)
        attempts = dict(ctx.conn.execute(
            "SELECT request_key, COUNT(*) FROM raw_responses WHERE source = ? AND ok = 0 "
            "AND error = ? GROUP BY request_key", (self.name, NOT_PUBLISHED)).fetchall())
        today = ctx.now.astimezone(IST).date()
        out = []
        d = end
        while d >= start:
            key = d.isoformat()
            given_up = (attempts.get(key, 0) >= GIVE_UP_AFTER_ATTEMPTS
                        and (today - d).days > GIVE_UP_AFTER_DAYS)
            if key not in have and not given_up:
                out.append(d)
            d -= timedelta(days=1)
        return out

    def _fetch(self, ctx: RunContext, dates: list[date]) -> list[RawRecord]:
        delay = float(ctx.config.source_settings(self.name).get("delay_seconds", 1.0))
        records = []
        for i, d in enumerate(dates):
            if i:
                ctx.sleep(delay)
            records.append(ctx.fetcher.get(
                self.name, URL, query={"id": bulletin_id(d)}, run_id=ctx.run_id,
                request_key=d.isoformat(), params={"date": d.isoformat()}, validate=validate_pdf,
            ))
        return records

    def collect(self, ctx: RunContext) -> list[RawRecord]:
        cap = int(ctx.config.source_settings(self.name).get("max_per_run", 30))
        missing = self.missing_dates(ctx)
        if len(missing) > cap:
            log.info("%s: %d dates missing; fetching newest %d (run `saans backfill %s` for all)",
                     self.name, len(missing), cap, self.name)
        return self._fetch(ctx, missing[:cap])

    def backfill(self, ctx: RunContext) -> list[RawRecord]:
        missing = self.missing_dates(ctx)
        log.info("%s: backfilling %d dates", self.name, len(missing))
        return self._fetch(ctx, missing)
