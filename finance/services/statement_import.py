"""Ingest a parsed statement into canonical JSONL storage — one path for every bank.

Statement exports carry no stable bank id, so rows are deduped on content —
(posting date, amount, normalised description) — which is what actually makes a
row the same event as a stored record. Rows already held in any year file are
left untouched, so previously categorised history keeps its categories. New
rows get aliases and rules applied on the way in.
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
from finance.models.transaction import TransactionRecord, utc_now_iso
from finance.services.journal import build_bank_journal
from finance.services.ledger import resolve_ledger_account
from finance.statements.model import StatementRow, StatementSummary
from finance.statements.parse import parse_statement
from finance.statements.profile import StatementProfile, load_profile
from finance.storage.alias_store import AliasStore, apply_aliases
from finance.storage.jsonl_store import JsonlTransactionStore
from finance.storage.rules_store import RulesStore, categorize_record


def normalize_description(description: str) -> str:
    """Comparison key for a description (unescape HTML, fold whitespace, upper)."""
    return " ".join(html.unescape(description or "").split()).upper()


def content_key(date: str, amount: str, description: str) -> tuple[str, str, str]:
    return date, f"{Decimal(amount):.2f}", normalize_description(description)


def _unknown_category(amount: str) -> str:
    return "expenses:unknown" if Decimal(amount) < 0 else "income:unknown"


def build_record_id(profile: StatementProfile, account: str, row: StatementRow, occurrence: int) -> str:
    """Stable id for a statement row.

    The running balance is part of the key so genuinely repeated rows (same day,
    merchant, amount) still get distinct ids; ``occurrence`` covers the case
    where even the balance repeats.
    """
    stable = "|".join(
        [row.date, row.action_date or "", row.description, row.amount, row.balance or "", account, str(occurrence)]
    )
    return f"{profile.id_prefix}:" + hashlib.sha256(stable.encode()).hexdigest()[:16]


def _build_record(
    bank: str, account: str, profile: StatementProfile, row: StatementRow, occurrence: int
) -> TransactionRecord:
    return TransactionRecord(
        id=build_record_id(profile, account, row, occurrence),
        institution=bank,
        source_account=account,
        ledger_account=resolve_ledger_account(bank, account),
        date=row.date,
        description=row.description,
        amount=row.amount,
        currency=profile.currency,
        category=_unknown_category(row.amount),
        category_source="default:unknown",
        status="cleared",
        imported_at=utc_now_iso(),
        payee=row.description,
        source_hash=hashlib.sha256(json.dumps(row.raw, sort_keys=True).encode()).hexdigest()[:16],
        provider_metadata={
            "importer": f"{profile.name}_{profile.format}",
            "action_date": row.action_date,
            "posting_date": row.date,
            "balance": row.balance,
            "reference": row.reference,
            "statement_line": row.line_number,
        },
    )


def _copy_raw_import(bank: str, source: Path) -> Path:
    config = load_app_config()
    target_dir = config.paths.imports_dir / bank
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    counter = 2
    while target.exists() and source.resolve() != target.resolve():
        target = target_dir / f"{source.stem}-{counter}{source.suffix}"
        counter += 1
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    return target


def _ensure_main_journal_include(main_journal: Path, include_path: str) -> None:
    content = main_journal.read_text() if main_journal.exists() else ""
    include_line = f"include {include_path}"
    if include_line in content:
        return
    if content and not content.endswith("\n"):
        content += "\n"
    main_journal.parent.mkdir(parents=True, exist_ok=True)
    main_journal.write_text(content + include_line + "\n")


def import_statement(
    file_path: str | Path,
    *,
    bank: str,
    account: str = "checking",
    profile: StatementProfile | None = None,
    dry_run: bool = False,
    copy_raw: bool = True,
    ai_fallback: bool = False,
) -> dict:
    """Parse and ingest a statement file for any bank.

    Parsing runs the balance-chain gate; a broken chain raises before anything
    is written. Existing rows (by content) are skipped so categories survive
    re-imports; new rows get aliases + rules applied. When ``ai_fallback`` is set,
    a PDF the deterministic parser can't handle is extracted via OpenAI and
    validated by the same balance chain.
    """
    source = Path(file_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    if profile is None:
        profile = load_profile(bank, account)

    rows, summary = parse_statement(source, profile, ai_fallback=ai_fallback)

    config = load_app_config()
    rules = RulesStore(config.paths.rules_config).load()
    aliases = AliasStore(config.paths.aliases_config).load()
    tx_store = JsonlTransactionStore(config.paths.transactions_dir)

    # Every stored record for this bank, keyed by content, so a row already held
    # in any year file (including one carrying a category) is never re-added.
    existing_keys: Counter = Counter()
    existing_ids: set[str] = set()
    bank_dir = config.paths.transactions_dir / bank
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
        record = _build_record(bank, account, profile, row, occurrence)
        while record.id in seen_ids or record.id in existing_ids:
            occurrence += 1
            record = _build_record(bank, account, profile, row, occurrence)
        record = apply_aliases(record, aliases)
        record = categorize_record(record, rules)
        record.validate()
        seen_ids.add(record.id)
        new_records.append(record)

    by_year: dict[int, list[TransactionRecord]] = defaultdict(list)
    for record in new_records:
        by_year[int(record.date[:4])].append(record)

    raw_copy = None
    journal_output = None
    if not dry_run and new_records:
        for year, year_records in by_year.items():
            tx_store.merge_file(config.paths.transaction_file(bank, year), year_records)
        _ensure_main_journal_include(config.paths.main_journal, f"generated/{bank}.journal")
        journal_output = build_bank_journal(bank)["output"]
    if not dry_run and copy_raw:
        raw_copy = str(_copy_raw_import(bank, source))

    return {
        "bank": bank,
        "account": account,
        "profile": profile.name,
        "format": profile.format,
        "summary": summary,
        "rows": len(rows),
        "inserted": len(new_records),
        "skipped_already_present": len(skipped),
        "counts_by_year": {year: len(records) for year, records in sorted(by_year.items())},
        "dry_run": dry_run,
        "raw_copy": raw_copy,
        "journal_output": journal_output,
    }


def format_import_result(result: dict) -> str:
    """Human-readable summary of an import result for the CLI."""
    summary: StatementSummary = result["summary"]
    lines = [
        f"Imported {result['bank']}[{result['account']}] via {result['profile']} ({result['format']}): "
        f"rows={result['rows']} inserted={result['inserted']} "
        f"already_present={result['skipped_already_present']} dry_run={result['dry_run']}",
    ]
    if summary.date_range:
        lines.append(f"Posting dates: {summary.date_range['start']} -> {summary.date_range['end']}")
    chain = "OK" if summary.balance_chain_verified else "not verified (no per-row balance)"
    lines.append(
        f"Balance chain: {chain}  opening={summary.opening_balance} closing={summary.closing_balance} "
        f"debits={summary.total_debits} credits={summary.total_credits}"
    )
    if result["counts_by_year"]:
        per_year = ", ".join(f"{year}: {count}" for year, count in result["counts_by_year"].items())
        lines.append(f"Inserted by year: {per_year}")
    if result["raw_copy"]:
        lines.append(f"Raw copy: {result['raw_copy']}")
    if result["journal_output"]:
        lines.append(f"Journal output: {result['journal_output']}")
    return "\n".join(lines)
