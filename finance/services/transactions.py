from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from finance.config import load_app_config
from finance.models.transaction import TransactionRecord, utc_now_iso
from finance.storage.jsonl_store import JsonlTransactionStore


def load_bank_transactions(bank: str) -> list[TransactionRecord]:
    config = load_app_config()
    bank_dir = config.paths.transactions_dir / bank
    store = JsonlTransactionStore(config.paths.transactions_dir)
    records: list[TransactionRecord] = []
    if not bank_dir.exists():
        return records
    for path in sorted(bank_dir.glob("*.jsonl")):
        records.extend(store.read_file(path))
    return sorted(records, key=lambda r: (r.date, r.id))


def filter_unknown_transactions(bank: str, category: str = "both") -> list[TransactionRecord]:
    records = load_bank_transactions(bank)
    if category == "expenses":
        return [r for r in records if r.category == "expenses:unknown"]
    if category == "income":
        return [r for r in records if r.category == "income:unknown"]
    return [r for r in records if r.category in {"expenses:unknown", "income:unknown"}]


def update_transaction_category(bank: str, txn_id: str, category: str, source: str = "manual") -> bool:
    config = load_app_config()
    store = JsonlTransactionStore(config.paths.transactions_dir)
    bank_dir = config.paths.transactions_dir / bank
    if not bank_dir.exists():
        return False

    updated_any = False
    for path in sorted(bank_dir.glob("*.jsonl")):
        records = store.read_file(path)
        changed = False
        for record in records:
            if record.id == txn_id:
                record.category = category
                record.category_source = source
                record.updated_at = utc_now_iso()
                changed = True
                updated_any = True
                break
        if changed:
            store.write_file(path, records)
            break
    return updated_any


def replace_transactions(bank: str, records: list[TransactionRecord]) -> None:
    config = load_app_config()
    store = JsonlTransactionStore(config.paths.transactions_dir)
    by_year: dict[int, list[TransactionRecord]] = defaultdict(list)
    for record in records:
        by_year[int(record.date[:4])].append(record)
    for year, year_records in by_year.items():
        store.write_file(config.paths.transaction_file(bank, year), year_records)
