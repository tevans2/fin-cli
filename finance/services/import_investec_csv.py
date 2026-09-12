"""Load an Investec statement CSV into canonical JSONL storage.

Investec's API import keys transactions on the bank's own uuid, which a CSV
export does not carry. So this importer dedupes on content instead —
(posting date, amount, normalised description) — which is what actually makes
a statement row the same event as a stored record. Rows that already exist in
any year file are left completely untouched, so previously categorized
history keeps its categories.
"""

from __future__ import annotations

import hashlib
import html
import json
import shutil
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from finance.config import load_app_config
from finance.importers.investec_csv import (
    BalanceChainError,
    InvestecCsvRow,
    build_record_id,
    parse_investec_csv,
    verify_balance_chain,
)
from finance.models.transaction import TransactionRecord, utc_now_iso
from finance.services.journal import build_bank_journal
from finance.storage.jsonl_store import JsonlTransactionStore

BANK = "investec"


def normalize_description(description: str) -> str:
    """Comparison key for a description.

    Older migrated records stored HTML-escaped text (``H&amp;M``) and the CSV
    pads merchant names with runs of spaces, so both are folded away.
    """
    return " ".join(html.unescape(description or "").split()).upper()


def content_key(date: str, amount: str, description: str) -> tuple[str, str, str]:
    return date, f"{Decimal(amount):.2f}", normalize_description(description)


def unknown_category(amount: str) -> str:
    return "expenses:unknown" if Decimal(amount) < 0 else "income:unknown"


def _resolve_ledger_account(account: str) -> str:
    config = load_app_config()
    bank_config = config.banks.get("banks", {}).get(BANK, {})
    configured = bank_config.get("ledger_account")
    if configured and account == bank_config.get("type"):
        return configured
    if configured and configured.endswith(":checking") and account == "savings":
        return configured[: -len(":checking")] + ":savings"
    return f"assets:bank:{BANK}:{account}"


def _copy_raw_import(source: Path) -> Path:
    config = load_app_config()
    target_dir = config.paths.imports_dir / BANK
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    counter = 2
    while target.exists() and source.resolve() != target.resolve():
        target = target_dir / f"{source.stem}-{counter}{source.suffix}"
        counter += 1
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    return target


def _build_record(row: InvestecCsvRow, account: str, occurrence: int) -> TransactionRecord:
    return TransactionRecord(
        id=build_record_id(row, account, occurrence),
        institution=BANK,
        source_account=account,
        ledger_account=_resolve_ledger_account(account),
        date=row.date,
        description=row.description,
        amount=row.amount,
        currency="ZAR",
        category=unknown_category(row.amount),
        category_source="default:unknown",
        status="cleared",
        imported_at=utc_now_iso(),
        payee=row.description,
        source_hash=hashlib.sha256(json.dumps(row.raw, sort_keys=True).encode()).hexdigest()[:16],
        provider_metadata={
            "importer": "investec_csv",
            "action_date": row.action_date,
            "posting_date": row.date,
            "balance": row.balance,
            "statement_line": row.line_number,
        },
    )


def import_investec_csv(
    csv_path: str | Path,
    *,
    account: str = "checking",
    dry_run: bool = False,
    copy_raw: bool = True,
) -> dict:
    source = Path(csv_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    rows, summary = parse_investec_csv(source)
    breaks = verify_balance_chain(rows)
    if breaks:
        detail = "; ".join(
            f"line {b['line']} ({b['date']} {b['description']}): expected {b['expected_balance']}, "
            f"got {b['actual_balance']}"
            for b in breaks[:5]
        )
        raise BalanceChainError(
            f"Statement running balance is inconsistent at {len(breaks)} row(s): {detail}"
        )

    config = load_app_config()
    tx_store = JsonlTransactionStore(config.paths.transactions_dir)

    # Every stored investec record, keyed by content, so a row already held in
    # any year file (including one carrying a category) is never re-added.
    existing_keys: Counter = Counter()
    existing_ids: set[str] = set()
    bank_dir = config.paths.transactions_dir / BANK
    if bank_dir.exists():
        for path in sorted(bank_dir.glob("*.jsonl")):
            for record in tx_store.read_file(path):
                existing_keys[content_key(record.date, record.amount, record.description)] += 1
                existing_ids.add(record.id)

    remaining = Counter(existing_keys)
    seen_ids: set[str] = set()
    new_records: list[TransactionRecord] = []
    skipped: list[dict] = []
    for row in rows:
        key = content_key(row.date, row.amount, row.description)
        if remaining[key] > 0:
            remaining[key] -= 1
            skipped.append({"date": row.date, "amount": row.amount, "description": row.description})
            continue
        occurrence = 0
        record = _build_record(row, account, occurrence)
        while record.id in seen_ids or record.id in existing_ids:
            occurrence += 1
            record = _build_record(row, account, occurrence)
        seen_ids.add(record.id)
        record.validate()
        new_records.append(record)

    by_year: dict[int, list[TransactionRecord]] = defaultdict(list)
    for record in new_records:
        by_year[int(record.date[:4])].append(record)

    raw_copy = None
    journal_result = None
    if not dry_run and new_records:
        for year, year_records in by_year.items():
            tx_store.merge_file(config.paths.transaction_file(BANK, year), year_records)
        journal_result = build_bank_journal(BANK)
    if not dry_run and copy_raw:
        raw_copy = str(_copy_raw_import(source))

    return {
        "bank": BANK,
        "account": account,
        "statement": summary,
        "balance_chain_ok": True,
        "rows": len(rows),
        "inserted": len(new_records),
        "skipped_already_present": len(skipped),
        "skipped_detail": skipped,
        "years": sorted(by_year.keys()),
        "counts_by_year": {year: len(records) for year, records in sorted(by_year.items())},
        "dry_run": dry_run,
        "raw_copy": raw_copy,
        "journal_output": journal_result["output"] if journal_result else None,
    }
