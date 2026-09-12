"""Thin, shared wrapper around the hledger binary.

Centralizes the ``hledger --no-conf -f <main.journal> ...`` invocation so the
CLI reports, the compare view, and the web UI don't each hand-roll it.
"""

from __future__ import annotations

import csv
import io
import subprocess

from finance.config import load_app_config


def _cmd(args: list[str]) -> list[str]:
    config = load_app_config()
    return ["hledger", "--no-conf", "-f", str(config.paths.main_journal), *args]


def run(args: list[str]) -> int:
    """Run hledger inheriting stdout/stderr (for CLI passthrough)."""
    return subprocess.run(_cmd(args)).returncode


def run_text(args: list[str]) -> tuple[int, str]:
    """Run hledger and capture combined stdout/stderr as text."""
    result = subprocess.run(_cmd(args), capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


def read_csv(args: list[str]) -> list[dict]:
    """Run hledger with CSV output and return parsed rows (empty on failure)."""
    result = subprocess.run(_cmd([*args, "-O", "csv"]), capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return list(csv.DictReader(io.StringIO(result.stdout)))
