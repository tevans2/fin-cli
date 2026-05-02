from __future__ import annotations

import subprocess

from finance.config import load_app_config


REPORTS = {
    "bs": ["balance"],
    "is": ["incomestatement"],
    "expenses": ["balance", "expenses"],
    "unknowns": ["register", "expenses:unknown|income:unknown"],
}


EXCLUDE_INVESTMENTS = ["not:assets:investments", "not:income:unrealised-gains"]


def run_hledger(args: list[str], exclude_investments: bool = True) -> int:
    config = load_app_config()
    extra = EXCLUDE_INVESTMENTS if exclude_investments else []
    cmd = ["hledger", "--no-conf", "-f", str(config.paths.main_journal), *args, *extra]
    result = subprocess.run(cmd)
    return result.returncode


def run_named_report(name: str) -> int:
    if name not in REPORTS:
        raise ValueError(f"Unknown report: {name}")
    return run_hledger(REPORTS[name])
