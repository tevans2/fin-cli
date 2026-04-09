from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from finance.config import load_app_config
from finance.models.state import BankSyncState
from finance.models.transaction import TransactionRecord, utc_now_iso
from finance.providers.investec import InvestecProvider
from finance.storage.alias_store import AliasStore, apply_aliases
from finance.storage.jsonl_store import JsonlTransactionStore
from finance.storage.rules_store import RulesStore, categorize_record
from finance.storage.state_store import SyncStateStore


def infer_unknown_category(amount: str) -> str:
    return "expenses:unknown" if Decimal(amount) < 0 else "income:unknown"


def determine_date_range(sync_state: BankSyncState | None, days_back: int = 7) -> tuple[str, str]:
    end_date = datetime.now().strftime("%Y-%m-%d")
    if sync_state and sync_state.last_successful_sync_date:
        start = datetime.strptime(sync_state.last_successful_sync_date, "%Y-%m-%d") + timedelta(days=1)
    else:
        start = datetime.now() - timedelta(days=days_back)
    return start.strftime("%Y-%m-%d"), end_date


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


def sync_bank(bank: str) -> dict:
    config = load_app_config()
    bank_config = config.banks.get("banks", {}).get(bank)
    if not bank_config:
        raise ValueError(f"Bank not configured: {bank}")

    if bank != "investec":
        raise ValueError("Only investec is supported in the first V2 slice")

    state_store = SyncStateStore(config.paths.sync_state)
    sync_state = state_store.load()
    bank_state = sync_state.banks.get(bank)
    start_date, end_date = determine_date_range(bank_state)

    provider = InvestecProvider(bank_config)
    fetched = provider.fetch_transactions(start_date, end_date)

    rules = RulesStore(config.paths.rules_config).load()
    aliases = AliasStore(config.paths.aliases_config).load()
    tx_store = JsonlTransactionStore(config.paths.transactions_dir)

    existing_by_id: dict[str, TransactionRecord] = {}
    bank_dir = config.paths.transactions_dir / bank
    if bank_dir.exists():
        for path in sorted(bank_dir.glob("*.jsonl")):
            for record in tx_store.read_file(path):
                existing_by_id[record.id] = record

    by_year: dict[int, list[TransactionRecord]] = defaultdict(list)
    for item in fetched:
        record = TransactionRecord(
            id=item.id,
            institution=bank,
            source_account=item.source_account,
            ledger_account=bank_config["ledger_account"],
            date=item.date,
            description=item.description,
            amount=item.amount,
            currency=item.currency,
            category=infer_unknown_category(item.amount),
            category_source="default:unknown",
            status=item.status,
            imported_at=utc_now_iso(),
            payee=item.payee,
            notes=None,
            tags=[],
            updated_at=None,
            source_hash=item.source_hash,
            provider_metadata=item.provider_metadata,
        )
        record = apply_aliases(record, aliases)
        existing = existing_by_id.get(record.id)
        if existing is None:
            record = categorize_record(record, rules)
        else:
            record = _preserve_user_fields(existing, record)
        by_year[int(record.date[:4])].append(record)

    inserted = 0
    updated = 0
    for year, rows in by_year.items():
        file_path = config.paths.transaction_file(bank, year)
        i, u = tx_store.merge_file(file_path, rows)
        inserted += i
        updated += u

    sync_state.banks[bank] = BankSyncState(last_successful_sync_date=end_date, cursor=None)
    state_store.save(sync_state)

    return {
        "bank": bank,
        "start_date": start_date,
        "end_date": end_date,
        "fetched": len(fetched),
        "inserted": inserted,
        "updated": updated,
        "years": sorted(by_year.keys()),
    }
