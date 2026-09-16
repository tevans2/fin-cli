"""The category taxonomy: the canonical set of valid category accounts.

Lives in the data repo at ``config/categories.yaml``. It validates every category
an assignment produces (catching typos and drift), powers autocomplete, and
grounds the LLM fallback's choices. An absent/empty taxonomy means "don't
enforce" — nothing breaks until you opt in by seeding one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from finance.models.transaction import TransactionRecord


@dataclass
class Taxonomy:
    categories: set[str] = field(default_factory=set)

    @property
    def enforced(self) -> bool:
        return bool(self.categories)

    def is_valid(self, category: str) -> bool:
        # "split" is a structural marker, always allowed; unenforced taxonomy allows all
        return category == "split" or not self.enforced or category in self.categories

    def sorted(self) -> list[str]:
        return sorted(self.categories)

    def roots(self) -> list[str]:
        return sorted({c.split(":", 1)[0] for c in self.categories})


def load_taxonomy(path: Path) -> Taxonomy:
    if not path.exists():
        return Taxonomy()
    data = yaml.safe_load(path.read_text()) or {}
    return Taxonomy(set(data.get("categories", []) or []))


def categories_in_use(records: list[TransactionRecord]) -> set[str]:
    """Every category account actually used across transactions and their splits."""
    used: set[str] = set()
    for record in records:
        if record.category and record.category != "split":
            used.add(record.category)
        for split in record.splits:
            if split.account:
                used.add(split.account)
    return used


def write_taxonomy(path: Path, categories: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"categories": sorted(categories)}, sort_keys=False))


def unlisted_categories(records: list[TransactionRecord], taxonomy: Taxonomy) -> set[str]:
    """Categories used by transactions that the taxonomy doesn't list (typos / new)."""
    if not taxonomy.enforced:
        return set()
    return {c for c in categories_in_use(records) if c not in taxonomy.categories}
