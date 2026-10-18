"""Command-line entrypoint: `saans run | collect | brief | reparse | backfill`."""

from __future__ import annotations

import argparse
import logging
import sys

from saans import __version__
from saans.config import ConfigError, load_config


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="saans", description="Delhi air-quality planner")
    p.add_argument("--config", help="path to config.yaml (default: ./config.yaml)")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"saans {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="collect from every source, then write today's brief")
    sub.add_parser("collect", help="collect from every source (no brief)")
    sub.add_parser("brief", help="write today's brief from what is already stored")
    sub.add_parser("reparse", help="rebuild parsed tables from the raw archive")
    bf = sub.add_parser("backfill", help="fetch history for a source that supports it")
    bf.add_argument("source")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not args.verbose:  # one line per request is noise; our own per-source summary suffices
        logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    from saans import runner  # imported late so `--help` stays fast

    return runner.dispatch(args.command, config, args)


if __name__ == "__main__":
    sys.exit(main())
