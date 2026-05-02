from __future__ import annotations

import json
from pathlib import Path

from finance.models.investment import InvestmentValuation


class InvestmentStore:
    def __init__(self, investments_dir: Path):
        self.investments_dir = investments_dir

    def _path(self, name: str) -> Path:
        return self.investments_dir / f"{name}.jsonl"

    def read(self, name: str) -> list[InvestmentValuation]:
        path = self._path(name)
        if not path.exists():
            return []
        rows: list[InvestmentValuation] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(InvestmentValuation.from_dict(json.loads(line)))
        return sorted(rows, key=lambda r: r.date)

    def append(self, valuation: InvestmentValuation) -> None:
        path = self._path(valuation.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(valuation.to_dict(), ensure_ascii=False) + "\n")

    def all_names(self) -> list[str]:
        if not self.investments_dir.exists():
            return []
        return sorted(p.stem for p in self.investments_dir.glob("*.jsonl"))
