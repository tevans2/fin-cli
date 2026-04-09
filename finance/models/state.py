from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BankSyncState:
    last_successful_sync_date: str | None = None
    cursor: str | None = None


@dataclass
class SyncState:
    schema_version: int = 1
    banks: dict[str, BankSyncState] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SyncState":
        banks = {
            name: BankSyncState(**state)
            for name, state in data.get("banks", {}).items()
        }
        return cls(schema_version=data.get("schema_version", 1), banks=banks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "banks": {
                name: {
                    "last_successful_sync_date": state.last_successful_sync_date,
                    "cursor": state.cursor,
                }
                for name, state in self.banks.items()
            },
        }
