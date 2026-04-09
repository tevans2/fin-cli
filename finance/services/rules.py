from __future__ import annotations

from finance.config import load_app_config
from finance.models.transaction import utc_now_iso
from finance.services.journal import build_bank_journal
from finance.services.transactions import load_bank_transactions, replace_transactions
from finance.storage.rules_store import RulesStore, categorize_record


def list_rules() -> list[dict]:
    config = load_app_config()
    rules = RulesStore(config.paths.rules_config).load()
    return [
        {
            "name": rule.name,
            "category": rule.category,
            "priority": rule.priority,
            "enabled": rule.enabled,
        }
        for rule in rules
    ]


def apply_rules(bank: str, include_manual: bool = False) -> dict:
    config = load_app_config()
    rules = RulesStore(config.paths.rules_config).load()
    records = load_bank_transactions(bank)
    updated = 0

    for record in records:
        if (not include_manual) and record.category_source == "manual":
            continue
        before = (record.category, record.category_source)
        categorize_record(record, rules)
        after = (record.category, record.category_source)
        if before != after:
            record.updated_at = utc_now_iso()
            updated += 1

    replace_transactions(bank, records)
    build_bank_journal(bank)
    return {"bank": bank, "updated": updated, "transactions": len(records)}
