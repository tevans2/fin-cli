from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path

from finance.config import load_app_config
from finance.importers.tyme_csv import TymeCsvFormatError, TymeCsvRow, build_tyme_record_id, parse_tyme_csv
from finance.models.transaction import TransactionRecord, utc_now_iso
from finance.services.journal import build_bank_journal
from finance.storage.alias_store import AliasStore, apply_aliases
from finance.storage.jsonl_store import JsonlTransactionStore
from finance.storage.rules_store import RulesStore, categorize_record


def infer_unknown_category(amount: str) -> str:
    return "expenses:unknown" if float(amount) < 0 else "income:unknown"


def _resolve_ledger_account(bank: str, account: str) -> str:
    config = load_app_config()
    bank_config = config.banks.get("banks", {}).get(bank, {})
    accounts = bank_config.get("accounts", {})
    if account in accounts and accounts[account].get("ledger_account"):
        return accounts[account]["ledger_account"]
    configured = bank_config.get("ledger_account")
    configured_type = bank_config.get("type")
    if configured and account == configured_type:
        return configured
    if configured and configured.endswith(":checking") and account == "savings":
        return configured[:-len(":checking")] + ":savings"
    return f"assets:bank:{bank}:{account}"


def _preserve_user_fields(existing: TransactionRecord | None, incoming: TransactionRecord) -> TransactionRecord:
    if existing is None:
        return incoming
    incoming.category = existing.category
    incoming.category_source = existing.category_source
    incoming.alias = existing.alias
    incoming.notes = existing.notes
    incoming.tags = existing.tags
    incoming.updated_at = existing.updated_at
    return incoming


def _copy_raw_import(bank: str, source: Path) -> Path:
    config = load_app_config()
    target_dir = config.paths.imports_dir / bank
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    if target.exists() and source.resolve() != target.resolve():
        stem = source.stem
        suffix = source.suffix
        counter = 2
        while True:
            candidate = target_dir / f"{stem}-{counter}{suffix}"
            if not candidate.exists():
                target = candidate
                break
            counter += 1
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    return target


def _build_record(bank: str, account: str, row: TymeCsvRow) -> TransactionRecord:
    ledger_account = _resolve_ledger_account(bank, account)
    record = TransactionRecord(
        id=build_tyme_record_id(row, account),
        institution=bank,
        source_account=account,
        ledger_account=ledger_account,
        date=row.date,
        description=row.description,
        amount=row.amount,
        currency="ZAR",
        category=infer_unknown_category(row.amount),
        category_source="default:unknown",
        status="cleared",
        imported_at=utc_now_iso(),
        payee=row.description,
        alias=None,
        notes=None,
        tags=[],
        updated_at=None,
        source_hash=hashlib.sha256(json.dumps(row.raw, sort_keys=True).encode()).hexdigest()[:16],
        provider_metadata={
            "importer": "tyme_csv",
            "reference": row.reference,
            "balance": row.balance,
            "raw_date": row.raw.get("Date") or row.raw.get("date"),
        },
    )
    return record


def import_tyme_csv(
    csv_path: str | Path,
    *,
    account: str = "checking",
    delimiter: str = ",",
    dry_run: bool = False,
    copy_raw: bool = True,
    date_column: str | None = None,
    description_column: str | None = None,
    amount_column: str | None = None,
    debit_column: str | None = None,
    credit_column: str | None = None,
    balance_column: str | None = None,
    reference_column: str | None = None,
) -> dict:
    source = Path(csv_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    mapping_overrides = {
        "date": date_column,
        "description": description_column,
        "amount": amount_column,
        "debit": debit_column,
        "credit": credit_column,
        "balance": balance_column,
        "reference": reference_column,
    }
    rows, mapping = parse_tyme_csv(source, account=account, delimiter=delimiter, mapping_overrides=mapping_overrides)

    config = load_app_config()
    rules = RulesStore(config.paths.rules_config).load()
    aliases = AliasStore(config.paths.aliases_config).load()
    tx_store = JsonlTransactionStore(config.paths.transactions_dir)

    existing_by_id: dict[str, TransactionRecord] = {}
    bank_dir = config.paths.transactions_dir / "tyme"
    if bank_dir.exists():
        for path in sorted(bank_dir.glob("*.jsonl")):
            for record in tx_store.read_file(path):
                existing_by_id[record.id] = record

    prepared: list[TransactionRecord] = []
    preview: list[dict] = []
    inserted = 0
    updated = 0
    unchanged = 0
    for row in rows:
        record = _build_record("tyme", account, row)
        record = apply_aliases(record, aliases)
        existing = existing_by_id.get(record.id)
        if existing is None:
            record = categorize_record(record, rules)
            inserted += 1
        else:
            record = _preserve_user_fields(existing, record)
            if existing.to_dict() != record.to_dict():
                updated += 1
            else:
                unchanged += 1
        prepared.append(record)
        if len(preview) < 5:
            preview.append({
                "date": record.date,
                "amount": record.amount,
                "description": record.description,
                "id": record.id,
            })

    by_year: dict[int, list[TransactionRecord]] = defaultdict(list)
    for record in prepared:
        by_year[int(record.date[:4])].append(record)

    raw_copy = None
    journal_result = None
    if not dry_run:
        if copy_raw:
            raw_copy = str(_copy_raw_import("tyme", source))
        for year, year_records in by_year.items():
            tx_store.merge_file(config.paths.transaction_file("tyme", year), year_records)
        _ensure_main_journal_include(config.paths.main_journal, "generated/tyme.journal")
        journal_result = build_bank_journal("tyme")

    date_range = None
    if rows:
        ordered_dates = sorted(row.date for row in rows)
        date_range = {"start": ordered_dates[0], "end": ordered_dates[-1]}

    return {
        "bank": "tyme",
        "account": account,
        "rows": len(rows),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "dry_run": dry_run,
        "mapping": mapping,
        "preview": preview,
        "date_range": date_range,
        "years": sorted(by_year.keys()),
        "raw_copy": raw_copy,
        "journal_output": journal_result["output"] if journal_result else None,
    }


def _ensure_main_journal_include(main_journal: Path, include_path: str) -> None:
    content = main_journal.read_text() if main_journal.exists() else ""
    include_line = f"include {include_path}"
    if include_line in content:
        return
    if content and not content.endswith("\n"):
        content += "\n"
    content += include_line + "\n"
    main_journal.write_text(content)
