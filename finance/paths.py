from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class DataDirError(Exception):
    pass


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def transactions_dir(self) -> Path:
        return self.root / "transactions"

    @property
    def journal_dir(self) -> Path:
        return self.root / "journal"

    @property
    def generated_journal_dir(self) -> Path:
        return self.journal_dir / "generated"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def runtime_dir(self) -> Path:
        return self.root / "runtime"

    @property
    def banks_config(self) -> Path:
        return self.config_dir / "banks.yaml"

    @property
    def rules_config(self) -> Path:
        return self.config_dir / "rules.yaml"

    @property
    def main_journal(self) -> Path:
        return self.journal_dir / "main.journal"

    @property
    def manual_journal(self) -> Path:
        return self.journal_dir / "manual.journal"

    @property
    def sync_state(self) -> Path:
        return self.state_dir / "sync.yaml"

    def transaction_file(self, bank: str, year: int) -> Path:
        return self.transactions_dir / bank / f"{year}.jsonl"

    def generated_journal(self, bank: str) -> Path:
        return self.generated_journal_dir / f"{bank}.journal"


def resolve_data_dir() -> Path:
    value = os.getenv("FIN_DATA_DIR")
    if not value:
        raise DataDirError(
            "FIN_DATA_DIR is not set. Point it at your separate finance data repo."
        )
    return Path(value).expanduser().resolve()


def get_data_paths() -> DataPaths:
    return DataPaths(resolve_data_dir())


def validate_data_dir(paths: DataPaths) -> list[str]:
    errors: list[str] = []
    required_dirs = [
        paths.config_dir,
        paths.transactions_dir,
        paths.journal_dir,
        paths.generated_journal_dir,
        paths.state_dir,
    ]
    for path in required_dirs:
        if not path.exists() or not path.is_dir():
            errors.append(f"Missing directory: {path}")

    required_files = [
        paths.banks_config,
        paths.rules_config,
        paths.main_journal,
        paths.manual_journal,
        paths.sync_state,
    ]
    for path in required_files:
        if not path.exists() or not path.is_file():
            errors.append(f"Missing file: {path}")

    return errors
