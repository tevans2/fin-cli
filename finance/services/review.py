from __future__ import annotations

from finance.config import load_app_config
from finance.models.transaction import TransactionRecord
from finance.services.journal import build_bank_journal
from finance.services.suggestions import suggest_category_for_record
from finance.services.transactions import (
    apply_alias_to_matching_descriptions,
    filter_unknown_transactions,
    update_transaction_alias,
    update_transaction_category,
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


def categorize_unknowns_interactively(bank: str, category: str = "both") -> dict:
    records = filter_unknown_transactions(bank, category)
    updated = 0
    skipped = 0
    aliases_created = 0

    index = 0
    while index < len(records):
        record = records[index]
        suggestion = suggest_category_for_record(bank, record)
        print()
        print(f"[{index + 1}/{len(records)}]")
        print(f"  date:        {record.date}")
        print(f"  amount:      {record.amount} {record.currency}")
        print(f"  source:      {record.ledger_account}")
        print(f"  txn_id:      {record.id}")
        print(f"  original:    {record.description}")
        print(f"  alias:       {record.alias or '-'}")
        print(f"  current:     {record.category}")
        print(f"  suggested:   {suggestion or '-'}")
        print("  actions:     [Enter=skip] [q=quit] [a=alias] [c=category]")
        action = input("  action: ").strip()

        if not action:
            skipped += 1
            index += 1
            continue
        if action.lower() == "q":
            break
        if action.lower() == "a":
            alias = input("  alias label: ").strip()
            if alias:
                create_alias(bank, record.id, record.description, alias)
                aliases_created += 1
                record.alias = alias
            continue

        category_value = action
        if action.lower() == "c":
            category_value = input(f"  category [{suggestion or ''}]: ").strip() or (suggestion or "")
        if not category_value:
            skipped += 1
            index += 1
            continue
        if update_transaction_category(bank, record.id, category_value, source="manual"):
            updated += 1
        index += 1

    build_bank_journal(bank)
    remaining = len(filter_unknown_transactions(bank, category))
    return {
        "updated": updated,
        "skipped": skipped,
        "aliases_created": aliases_created,
        "remaining": remaining,
    }
