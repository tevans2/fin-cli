from __future__ import annotations

from finance.config import load_app_config
from finance.models.transaction import TransactionRecord
from finance.services.transactions import (
    apply_alias_to_matching_descriptions,
    filter_unknown_transactions,
    update_transaction_alias,
)
from finance.storage.alias_store import AliasStore


def review_unknowns(bank: str, category: str = "both") -> list[TransactionRecord]:
    return filter_unknown_transactions(bank, category)


def create_alias(bank: str, txn_id: str, description: str, alias: str) -> int:
    config = load_app_config()
    store = AliasStore(config.paths.aliases_config)
    store.add_exact_alias(description, alias)
    update_transaction_alias(bank, txn_id, alias)
    return apply_alias_to_matching_descriptions(bank, description, alias)
