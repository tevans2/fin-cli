from __future__ import annotations

from pathlib import Path


class JournalStore:
    def __init__(self, path: Path):
        self.path = path

    def write(self, content: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(content)
