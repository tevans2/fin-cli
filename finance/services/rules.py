from __future__ import annotations

import re

from finance.config import load_app_config
from finance.models.rules import Rule, RuleMatch
from finance.models.transaction import utc_now_iso
from finance.services.journal import build_bank_journal
from finance.services.transactions import load_bank_transactions, replace_transactions
from finance.storage.rules_store import RulesStore, categorize_record


def create_rule(
    category: str,
    *,
    merchant: str | None = None,
    description_regex: str | None = None,
    account: str | None = None,
    institution: str | None = None,
    direction: str | None = None,
    amount_lt: str | None = None,
    amount_gt: str | None = None,
    currency: str | None = None,
    name: str | None = None,
    priority: int = 50,
) -> str:
    """Append a categorization rule and return its (unique) name.

    Priority defaults to 50 so user rules win over the priority-1000 unknown
    fallbacks. At least one match condition is required.
    """
    match = RuleMatch(
        merchant=merchant.strip().lower() if merchant else None,
        description_regex=description_regex,
        account=account,
        institution=institution,
        direction=direction,
        amount_lt=amount_lt,
        amount_gt=amount_gt,
        currency=currency,
    )
    if all(getattr(match, f) in (None, "") for f in RuleMatch.__dataclass_fields__):
        raise ValueError("a rule needs at least one match condition")

    config = load_app_config()
    store = RulesStore(config.paths.rules_config)
    base = name or "rule-" + re.sub(r"[^a-z0-9]+", "-", (merchant or description_regex or category).lower()).strip("-")
    existing = store.names()
    final = base
    suffix = 2
    while final in existing:
        final = f"{base}-{suffix}"
        suffix += 1
    store.add_rule(Rule(name=final, category=category, priority=priority, match=match))
    return final


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
