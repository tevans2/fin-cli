from __future__ import annotations

import re
from pathlib import Path

import yaml

from finance.models.alias import AliasRule
from finance.models.transaction import TransactionRecord


class AliasStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[AliasRule]:
        if not self.path.exists():
            return []
        with open(self.path) as f:
            data = yaml.safe_load(f) or {}
        return [AliasRule.from_dict(item) for item in data.get("aliases", []) if item.get("enabled", True)]

    def save(self, aliases: list[AliasRule]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"aliases": [alias.to_dict() for alias in aliases]}
        with open(self.path, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)

    def add_exact_alias(self, description: str, alias_text: str) -> AliasRule:
        aliases = self.load()
        name = re.sub(r"[^a-z0-9]+", "-", alias_text.lower()).strip("-") or "alias"
        rule = AliasRule(
            name=f"alias-{name}",
            alias=alias_text,
            description_exact=description,
            enabled=True,
            notes=f"Alias for exact description: {description}",
        )
        aliases = [a for a in aliases if not (a.description_exact == description and a.alias == alias_text)]
        aliases.append(rule)
        self.save(aliases)
        return rule


def apply_aliases(record: TransactionRecord, aliases: list[AliasRule]) -> TransactionRecord:
    for alias in aliases:
        if alias.description_exact and record.description == alias.description_exact:
            record.alias = alias.alias
            return record
        if alias.description_regex and re.search(alias.description_regex, record.description, re.IGNORECASE):
            record.alias = alias.alias
            return record
    return record
