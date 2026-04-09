from __future__ import annotations

from pathlib import Path

from finance.config import load_app_config
from finance.models.transaction import TransactionRecord
from finance.storage.journal_store import JournalStore
from finance.storage.jsonl_store import JsonlTransactionStore


def _status_marker(status: str) -> str:
    return "*" if status == "cleared" else "!"


def _commodity_symbol(currency: str) -> str:
    return {
        "ZAR": "R",
        "USD": "$",
    }.get(currency, currency + " ")


def _format_amount(amount: str, currency: str) -> str:
    return f"{_commodity_symbol(currency)}{float(amount):.2f}"


def _render_transaction(record: TransactionRecord) -> str:
    description = record.payee or record.description
    opposite_amount = f"{-float(record.amount):.2f}"
    return (
        f"{record.date} {_status_marker(record.status)} {description}  ; txn_id: {record.id}\n"
        f"    {record.ledger_account}    {_format_amount(record.amount, record.currency)}\n"
        f"    {record.category}    {_format_amount(opposite_amount, record.currency)}\n"
    )


def build_bank_journal(bank: str) -> dict:
    config = load_app_config()
    tx_store = JsonlTransactionStore(config.paths.transactions_dir)
    bank_dir = config.paths.transactions_dir / bank
    if not bank_dir.exists():
        records: list[TransactionRecord] = []
    else:
        records = []
        for path in sorted(bank_dir.glob("*.jsonl")):
            records.extend(tx_store.read_file(path))
        records.sort(key=lambda r: (r.date, r.id))

    header = f"; Generated journal for {bank}\n; Do not edit directly\n\n"
    body = "\n".join(_render_transaction(record).rstrip() for record in records)
    content = header + (body + "\n" if body else "")
    output_path = config.paths.generated_journal(bank)
    JournalStore(output_path).write(content)
    return {"bank": bank, "transactions": len(records), "output": str(output_path)}
