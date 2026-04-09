from __future__ import annotations

from collections import Counter

from finance.models.transaction import TransactionRecord
from finance.services.transactions import load_bank_transactions


def suggest_category_for_record(bank: str, record: TransactionRecord) -> str | None:
    records = load_bank_transactions(bank)
    candidates = []

    # 1. exact alias matches
    if record.alias:
        candidates.extend(
            r.category
            for r in records
            if r.id != record.id and r.alias and r.alias == record.alias and r.category not in {"expenses:unknown", "income:unknown"}
        )

    # 2. exact description matches
    if not candidates:
        candidates.extend(
            r.category
            for r in records
            if r.id != record.id and r.description == record.description and r.category not in {"expenses:unknown", "income:unknown"}
        )

    if not candidates:
        return None
    return Counter(candidates).most_common(1)[0][0]
