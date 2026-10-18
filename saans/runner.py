"""Orchestrates a Saans run. Filled in as Phase 1 lands."""

from __future__ import annotations

import argparse
import logging

from saans.config import Config

log = logging.getLogger(__name__)


def dispatch(command: str, config: Config, args: argparse.Namespace) -> int:
    log.error("`saans %s` is not implemented yet", command)
    return 1
