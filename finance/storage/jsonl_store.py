from __future__ import annotations

import json
from pathlib import Path

from finance.models.transaction import TransactionRecord


class JsonlTransactionStore:
    def __init__(self, root: Path):
        self.root = root

    def read_file(self, path: Path) -> list[TransactionRecord]:
        if not path.exists():
            return []
        rows: list[TransactionRecord] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(TransactionRecord.from_dict(json.loads(line)))
        return rows

    def write_file(self, path: Path, records: list[TransactionRecord]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        sorted_records = sorted(records, key=lambda r: (r.date, r.id))
        with open(path, "w") as f:
            for record in sorted_records:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def merge_file(self, path: Path, incoming: list[TransactionRecord]) -> tuple[int, int]:
        existing = {record.id: record for record in self.read_file(path)}
        inserted = 0
        updated = 0
        for record in incoming:
            current = existing.get(record.id)
            if current is None:
                existing[record.id] = record
                inserted += 1
            elif current.to_dict() != record.to_dict():
                existing[record.id] = record
                updated += 1
        self.write_file(path, list(existing.values()))
        return inserted, updated
