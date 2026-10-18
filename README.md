# Saans (साँस, "breath")

A personal air-quality planner for Delhi. Instead of just reporting the AQI, it tells you what
to do today: when to train outdoors, when to air out the house, when to leave for the office and
when to switch the car to recirculation. It also warns of stubble-smoke spikes 24–48 h ahead, and
keeps an honest scorecard of whose AQI forecasts are actually right.

Uses India's CPCB NAQI scale throughout.

- [ROADMAP.md](ROADMAP.md): phases and their definitions of done
- [DATA_SOURCES.md](DATA_SOURCES.md): every data source, tested, with gaps
- [DECISIONS.md](DECISIONS.md): product and technical decision log
- [CLAUDE.md](CLAUDE.md): project conventions

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cp .env.example .env            # optional keys; see DATA_SOURCES.md
.venv/bin/saans run             # collect everything, write out/brief-YYYY-MM-DD.{md,html}
```

Other commands: `saans collect`, `saans brief`, `saans reparse` (rebuild parsed tables from the
raw archive), `saans backfill cpcb_bulletin` (fetch the bulletin archive back to Oct 2025).
Tests run fully offline: `.venv/bin/pytest`.

Status: Phase 1 (collector + brief scaffold). Recommendations arrive in Phase 2.

Data: Open-Meteo (CC BY 4.0), CAMS, CPCB, NASA FIRMS, OpenAQ, WAQI, IITM, credited as each is
integrated.
