# Saans: project conventions

Saans is a personal, Delhi-specific air-quality planner. It tells one user (home in Model Town,
office in Noida, commutes by car) what to *do* each day. See ROADMAP.md for phases,
DATA_SOURCES.md for every external source, DECISIONS.md for why things are the way they are.

## Non-negotiables
- **CPCB NAQI, never US AQI**, for anything shown to the user or scored. Third-party AQI numbers
  (WAQI, Open-Meteo's `us_aqi`) are converted, or used only as pollutant concentrations.
- **Never invent an endpoint.** A new source or endpoint goes into DATA_SOURCES.md with its doc
  link and a successful test date *before* any code uses it.
- **Raw first.** Every response is saved to `data/raw/` and indexed before it's parsed.
  Parsers must be re-runnable from raw (`saans reparse`). Never mutate or delete raw files.
- **Tests never touch the network.** Fixtures are real recorded responses in `tests/fixtures/<source>/`
  with secrets scrubbed. The socket is blocked in pytest.
- **Public repo hygiene:** no secrets, no exact addresses (locality-level coordinates only, rounded to
  2 decimals), and no collected data (`data/`, `out/` are gitignored; WAQI terms forbid
  redistributing cached data). Strip keys from any URL before logging or storing it.
- **Log meaningful decisions** in DECISIONS.md (options, choice, why, revisit trigger) in the same
  commit as the change. This log is a portfolio artifact; keep it honest, including reversals.

## Stack
- Python 3.12, plain `venv` + `pip`, `pyproject.toml`. Install: `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`
- SQLite (`data/saans.db`), plain SQL with small migration files in `saans/migrations/`. No ORM.
- HTTP: `httpx`. Test mocking: `respx`. Network blocked in tests: `pytest-socket`.
- Config: `config.yaml` (committed, non-secret). Secrets: `.env` (gitignored), template in `.env.example`.
- The CLI entrypoint `saans` (`run`, `collect`, `brief`, `reparse`). No macOS-specific code in the
  package; launchd lives only in `ops/` (the plan is to host it later, see D-006).

## Layout (target)
```
saans/            package
  cli.py          entrypoints
  config.py       loads config.yaml + .env
  db.py           connection + migrations
  raw.py          fetch → store raw → index row
  naqi.py         CPCB NAQI (pure, table-driven)
  sources/        one module per source: fetch() + parse()
  brief/          plan logic + Markdown/HTML rendering
tests/            mirrors saans/; fixtures/ holds recorded responses
docs/             heuristic write-ups, backtests
ops/              launchd template (not installed by default)
data/ out/        gitignored: DB, raw archive, generated briefs
```

## Conventions
- Store timestamps as **UTC ISO-8601** and display them in **Asia/Kolkata**. Every forecast row
  has `issued_at` and `valid_at`.
- One source = one module with `fetch(ctx) -> list[RawRecord]` and `parse(raw) -> rows`. A source
  failing or missing its key logs and is skipped; it must never break the run.
- Units: µg/m³ for everything except CO in mg/m³ (the NAQI convention). Convert at parse time and name
  the columns with units (`pm25_ugm3`).
- Every recommendation in the brief carries a human-readable reason with the numbers that drove it.
- Small increments; each one runs and passes tests before it's committed. Use conventional commit
  prefixes (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).

## The user
SDET background: cares about tests, clean structure and explicit decisions. Uses the project
as a product-management portfolio piece.
