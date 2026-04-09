from __future__ import annotations

from finance.models.transaction import TransactionRecord
from finance.services.journal import build_bank_journal
from finance.services.transactions import filter_unknown_transactions, update_transaction_category


def review_unknowns(bank: str, category: str = "both") -> list[TransactionRecord]:
    return filter_unknown_transactions(bank, category)


def categorize_unknowns_interactively(bank: str, category: str = "both") -> dict:
    records = filter_unknown_transactions(bank, category)
    updated = 0
    skipped = 0

    index = 0
    while index < len(records):
        record = records[index]
        print()
        print(f"[{index + 1}/{len(records)}] {record.date} {record.description}")
        print(f"  amount:   {record.amount} {record.currency}")
        print(f"  current:  {record.category}")
        print(f"  txn_id:   {record.id}")
        new_category = input("  new category (Enter=skip, q=quit): ").strip()
        if not new_category:
            skipped += 1
            index += 1
            continue
        if new_category.lower() == "q":
            break
        if update_transaction_category(bank, record.id, new_category, source="manual"):
            updated += 1
        index += 1

    build_bank_journal(bank)
    remaining = len(filter_unknown_transactions(bank, category))
    return {
        "updated": updated,
        "skipped": skipped,
        "remaining": remaining,
    }
