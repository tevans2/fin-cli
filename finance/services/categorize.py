"""Shared categorization helpers used by both the TUI and the web UI.

The business logic (mutating transactions, suggesting categories, creating
aliases) already lives in `transactions`, `suggestions`, and `review`. This
module only adds the small UI-agnostic pieces both front-ends need: account
gathering and fuzzy ranking for the account picker, plus a view-model builder
for a single unknown transaction.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from finance.config import load_app_config
from finance.models.transaction import TransactionRecord
from finance.services.suggestions import suggest_category_for_record
from finance.services.transactions import load_bank_transactions
from finance.storage.accounts_store import AccountsStore

UNKNOWN_CATEGORIES = {"expenses:unknown", "income:unknown"}


def score(query: str, candidate: str) -> float:
    """Rank a candidate account against a query. Higher is better."""
    if not query:
        return 1.0
    q = query.lower()
    c = candidate.lower()
    if q in c:
        return 2.0 + (len(q) / max(len(c), 1))
    return SequenceMatcher(None, q, c).ratio()


def gather_accounts(bank: str) -> list[str]:
    """Declared accounts if available, else accounts seen in this bank's data."""
    config = load_app_config()
    declared = AccountsStore(config.paths.accounts_config).load()
    if declared:
        return declared

    accounts: set[str] = set()
    for record in load_bank_transactions(bank):
        accounts.add(record.ledger_account)
        if record.category not in UNKNOWN_CATEGORIES:
            accounts.add(record.category)
    return sorted(accounts)


def filter_accounts(accounts: list[str], query: str, limit: int = 50) -> list[str]:
    ranked = sorted(accounts, key=lambda c: score(query, c), reverse=True)
    return [c for c in ranked if score(query, c) > 0.25][:limit]


def suggestion_for(bank: str, record: TransactionRecord) -> str | None:
    """Best guess category for a record, mirroring the TUI's logic."""
    suggested = suggest_category_for_record(bank, record)
    if suggested and suggested not in UNKNOWN_CATEGORIES:
        return suggested
    if record.category not in UNKNOWN_CATEGORIES:
        return record.category
    return None


def list_banks() -> list[str]:
    """Bank names that have a transactions directory."""
    config = load_app_config()
    txn_dir = config.paths.transactions_dir
    if not txn_dir.exists():
        return []
    return sorted(
        d.name
        for d in txn_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )
