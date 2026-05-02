from __future__ import annotations

import subprocess

from finance.config import load_app_config


REPORTS = {
    "bs": ["balance"],
    "is": ["incomestatement"],
    "expenses": ["balance", "expenses"],
    "unknowns": ["register", "expenses:unknown|income:unknown"],
}

CASHFLOW_FILTERS = ["not:assets:investments", "not:income:unrealised-gains"]
INVESTMENTS_FILTERS = ["assets:investments", "income:unrealised-gains"]


def run_hledger(args: list[str]) -> int:
    config = load_app_config()
    cmd = ["hledger", "--no-conf", "-f", str(config.paths.main_journal), *args]
    result = subprocess.run(cmd)
    return result.returncode


def run_cashflow(args: list[str]) -> int:
    return run_hledger([*args, *CASHFLOW_FILTERS])


def run_investments(args: list[str]) -> int:
    return run_hledger([*args, *INVESTMENTS_FILTERS])


def run_named_report(name: str) -> int:
    if name not in REPORTS:
        raise ValueError(f"Unknown report: {name}")
    return run_hledger(REPORTS[name])
