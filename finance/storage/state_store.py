from __future__ import annotations

from pathlib import Path

import yaml

from finance.models.state import SyncState


class SyncStateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> SyncState:
        if not self.path.exists():
            return SyncState()
        with open(self.path) as f:
            data = yaml.safe_load(f) or {}
        return SyncState.from_dict(data)

    def save(self, state: SyncState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            yaml.safe_dump(state.to_dict(), f, sort_keys=False)
