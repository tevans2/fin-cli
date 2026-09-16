"""Assisted categorization: auto-apply the sure things, recommend the rest.

`build_plan` classifies a bank's uncategorized transactions (recommendation +
ranked candidates + auto flag). `auto_apply` commits just the confident ones in a
single write. The CLI drives the manual remainder, pre-filling the recommendation
so accepting is one keystroke and splitting is quick.
"""

from __future__ import annotations

from finance.classify.allocation import Allocation, to_splits, validate_allocations
from finance.classify.engine import Classification, classify
from finance.classify.history import UNKNOWN_CATEGORIES, build_history
from finance.config import load_app_config
from finance.models.transaction import TransactionRecord, utc_now_iso
from finance.services.journal import build_bank_journal
from finance.services.transactions import (
    filter_unknown_transactions,
    load_all_transactions,
    load_bank_transactions,
    replace_transactions,
    update_transaction_category,
    update_transaction_splits,
)
from finance.storage.rules_store import RulesStore


def _rules():
    return RulesStore(load_app_config().paths.rules_config).load()


def build_plan(bank: str) -> list[tuple[TransactionRecord, Classification]]:
    """Uncategorized transactions for a bank, each with its recommendation."""
    history = build_history(load_all_transactions())   # cross-bank learning
    rules = _rules()
    return [(record, classify(record, history=history, rules=rules)) for record in filter_unknown_transactions(bank)]


def auto_apply(bank: str) -> dict:
    """Apply only the confident classifications, in one write, then rebuild the journal."""
    history = build_history(load_all_transactions())
    rules = _rules()
    records = load_bank_transactions(bank)

    applied = 0
    for record in records:
        if record.category not in UNKNOWN_CATEGORIES:
            continue
        result = classify(record, history=history, rules=rules)
        if result.auto and result.recommended:
            record.category = result.recommended
            record.category_source = result.source
            if result.merchant:
                record.merchant = result.merchant
            record.updated_at = utc_now_iso()
            applied += 1

    if applied:
        replace_transactions(bank, records)
        build_bank_journal(bank)

    remaining = len(filter_unknown_transactions(bank))
    return {"bank": bank, "auto_applied": applied, "remaining": remaining}


def apply_category(bank: str, txn_id: str, category: str, *, source: str = "manual", merchant: str | None = None) -> bool:
    return update_transaction_category(bank, txn_id, category, source=source, merchant=merchant)


def apply_splits(
    bank: str, record: TransactionRecord, allocations: list[Allocation], *, merchant: str | None = None
) -> bool:
    validate_allocations(allocations, record.amount)   # every cent in one category, sums exactly
    return update_transaction_splits(bank, record.id, to_splits(allocations), merchant=merchant)


def rebuild_journal(bank: str) -> None:
    build_bank_journal(bank)
