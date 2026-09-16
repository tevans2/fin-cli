from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import yaml

from finance.models.rules import Rule
from finance.models.transaction import TransactionRecord


class RulesStore:
    def __init__(self, path: Path):
        self.path = path

    def _read_raw(self) -> dict:
        if not self.path.exists():
            return {"rules": []}
        with open(self.path) as f:
            return yaml.safe_load(f) or {"rules": []}

    def load(self) -> list[Rule]:
        data = self._read_raw()
        rules = [Rule.from_dict(item) for item in data.get("rules", [])]
        return sorted([rule for rule in rules if rule.enabled], key=lambda r: r.priority)

    def names(self) -> set[str]:
        return {item.get("name") for item in self._read_raw().get("rules", []) if item.get("name")}

    def add_rule(self, rule: Rule) -> None:
        """Append a rule, preserving the existing file (including disabled rules)."""
        data = self._read_raw()
        data.setdefault("rules", []).append(rule.to_dict())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)


def match_rule(rule: Rule, record: TransactionRecord) -> bool:
    match = rule.match
    if match.description_regex and not re.search(match.description_regex, record.description, re.IGNORECASE):
        return False
    if match.merchant:
        from finance.classify.normalize import merchant_key

        if merchant_key(record.description) != match.merchant.strip().lower():
            return False
    if match.account is not None and record.source_account != match.account:
        return False
    if match.institution is not None and record.institution != match.institution:
        return False
    amount = Decimal(record.amount)
    if match.direction == "out" and not amount < 0:
        return False
    if match.direction == "in" and not amount > 0:
        return False
    if match.amount_lt is not None and not (amount < Decimal(match.amount_lt)):
        return False
    if match.amount_gt is not None and not (amount > Decimal(match.amount_gt)):
        return False
    if match.currency is not None and record.currency != match.currency:
        return False
    return True


def categorize_record(record: TransactionRecord, rules: list[Rule]) -> TransactionRecord:
    for rule in rules:
        if match_rule(rule, record):
            record.category = rule.category
            record.category_source = f"rule:{rule.name}"
            return record
    return record
