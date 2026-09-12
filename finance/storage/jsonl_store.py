from __future__ import annotations

import json
import os
import tempfile
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
        payload = "".join(
            json.dumps(record.to_dict(), ensure_ascii=False) + "\n"
            for record in sorted_records
        )
        # Write to a temp file in the same directory, then atomically replace, so
        # a crash mid-write can never corrupt an existing year file (the source
        # of truth). os.replace is atomic on the same filesystem.
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise

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
