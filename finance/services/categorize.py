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
    clear_transaction_category,
    filter_unknown_transactions,
    load_all_transactions,
    load_bank_transactions,
    replace_transactions,
    set_reviewed,
    update_transaction_category,
    update_transaction_splits,
)
from finance.storage.rules_store import RulesStore


def _rules():
    return RulesStore(load_app_config().paths.rules_config).load()


def _review_records(bank: str) -> list[TransactionRecord]:
    """Auto-classified transactions awaiting review (categorized but reviewed=False)."""
    return [
        r for r in load_bank_transactions(bank)
        if not r.reviewed and r.category not in UNKNOWN_CATEGORIES
    ]


def build_plan(
    bank: str, *, scope: str = "uncat", history=None, rules=None
) -> list[tuple[TransactionRecord, Classification]]:
    """Transactions to act on for a scope, each with its recommendation/candidates.

    scope 'uncat' = uncategorized inbox; 'review' = auto-guesses awaiting review;
    'all' = every transaction (newest first), for browsing/re-categorizing.
    Pass a prebuilt ``history``/``rules`` (e.g. a cached Classifier) to skip the
    rebuild and stay fast.
    """
    if history is None:
        history = build_history(load_all_transactions())   # cross-bank learning
    if rules is None:
        rules = _rules()
    if scope == "review":
        records = _review_records(bank)
    elif scope == "all":
        records = sorted(load_bank_transactions(bank), key=lambda r: r.date, reverse=True)
    else:
        records = filter_unknown_transactions(bank)
    return [(record, classify(record, history=history, rules=rules)) for record in records]


def auto_apply(bank: str, *, history=None, rules=None) -> dict:
    """Apply only the confident classifications (as reviewed=False), in one write."""
    if history is None:
        history = build_history(load_all_transactions())
    if rules is None:
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
            record.reviewed = False   # auto-guess -> goes to the review queue
            if result.merchant:
                record.merchant = result.merchant
            record.updated_at = utc_now_iso()
            applied += 1

    if applied:
        replace_transactions(bank, records)
        build_bank_journal(bank)

    return {
        "bank": bank,
        "auto_applied": applied,
        "remaining": len(filter_unknown_transactions(bank)),
        "needs_review": len(_review_records(bank)),
    }


def confirm(bank: str, txn_ids: list[str]) -> int:
    """Mark auto-classifications as reviewed (drops them from the review queue)."""
    return set_reviewed(bank, set(txn_ids), True)


def reject(bank: str, txn_id: str) -> bool:
    """Reject a classification: reset the transaction to uncategorized."""
    ok = clear_transaction_category(bank, txn_id)
    if ok:
        build_bank_journal(bank)
    return ok


def apply_category(bank: str, txn_id: str, category: str, *, source: str = "manual", merchant: str | None = None) -> bool:
    return update_transaction_category(bank, txn_id, category, source=source, merchant=merchant)


def apply_splits(
    bank: str, record: TransactionRecord, allocations: list[Allocation], *, merchant: str | None = None
) -> bool:
    validate_allocations(allocations, record.amount)   # every cent in one category, sums exactly
    return update_transaction_splits(bank, record.id, to_splits(allocations), merchant=merchant)


def rebuild_journal(bank: str) -> None:
    build_bank_journal(bank)
