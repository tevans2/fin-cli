from __future__ import annotations

from pathlib import Path
import yaml


DEFAULT_BANKS = {
    "banks": {
        "investec": {
            "name": "Investec",
            "type": "checking",
            "default_currency": "ZAR",
            "ledger_account": "assets:bank:investec:checking",
            "api": {
                "timeout_seconds": 30,
                "retry_attempts": 3,
                "retry_delay_seconds": 5,
            },
        }
    }
}

DEFAULT_RULES = {
    "rules": [
        {
            "name": "default-expense-unknown",
            "category": "expenses:unknown",
            "priority": 1000,
            "enabled": True,
            "notes": "Fallback expense category",
            "match": {"amount_lt": "0"},
        },
        {
            "name": "default-income-unknown",
            "category": "income:unknown",
            "priority": 1000,
            "enabled": True,
            "notes": "Fallback income category",
            "match": {"amount_gt": "0"},
        },
    ]
}

DEFAULT_SYNC_STATE = {
    "schema_version": 1,
    "banks": {},
}

DEFAULT_MAIN_JOURNAL = "; V2 main journal\n\ninclude manual.journal\ninclude generated/investec.journal\n"
DEFAULT_MANUAL_JOURNAL = "; Manual finance entries\n"
DEFAULT_GITIGNORE = "logs/\ntmp/\nraw/\nnormalized/\ncache/\n*.wal\n*.shm\nruntime/\n"
DEFAULT_GITATTRIBUTES = "config/** filter=git-crypt diff=git-crypt\ntransactions/** filter=git-crypt diff=git-crypt\njournal/** filter=git-crypt diff=git-crypt\nstate/** filter=git-crypt diff=git-crypt\n"


def initialize_data_dir(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for rel in [
        "config",
        "transactions",
        "journal",
        "journal/generated",
        "state",
        "runtime",
    ]:
        (target / rel).mkdir(parents=True, exist_ok=True)

    with open(target / "config" / "banks.yaml", "w") as f:
        yaml.safe_dump(DEFAULT_BANKS, f, sort_keys=False)
    with open(target / "config" / "rules.yaml", "w") as f:
        yaml.safe_dump(DEFAULT_RULES, f, sort_keys=False)
    with open(target / "state" / "sync.yaml", "w") as f:
        yaml.safe_dump(DEFAULT_SYNC_STATE, f, sort_keys=False)

    (target / "journal" / "main.journal").write_text(DEFAULT_MAIN_JOURNAL)
    (target / "journal" / "manual.journal").write_text(DEFAULT_MANUAL_JOURNAL)
    (target / ".gitignore").write_text(DEFAULT_GITIGNORE)
    (target / ".gitattributes").write_text(DEFAULT_GITATTRIBUTES)
