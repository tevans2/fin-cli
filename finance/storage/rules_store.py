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

    def load(self) -> list[Rule]:
        if not self.path.exists():
            return []
        with open(self.path) as f:
            data = yaml.safe_load(f) or {}
        rules = [Rule.from_dict(item) for item in data.get("rules", [])]
        return sorted([rule for rule in rules if rule.enabled], key=lambda r: r.priority)


def match_rule(rule: Rule, record: TransactionRecord) -> bool:
    match = rule.match
    if match.description_regex and not re.search(match.description_regex, record.description, re.IGNORECASE):
        return False
    amount = Decimal(record.amount)
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
