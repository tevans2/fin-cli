"""Rename / merge a category everywhere it appears (a safe data migration).

A category account is referenced in several places: transaction records (the
`category` field and split accounts), the taxonomy, and the hand-written journals
and config (accounts.journal, budget, manual.journal, rules). Renaming has to
touch all of them consistently. It is token-safe: `expenses:holiday` is never
rewritten inside `expenses:holiday:accommodation`. If the target already exists,
a rename is effectively a merge.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from finance.config import load_app_config
from finance.models.transaction import utc_now_iso
from finance.services.journal import build_bank_journal
from finance.services.transactions import load_bank_transactions, replace_transactions


def replace_account_token(text: str, old: str, new: str) -> str:
    """Replace `old` only where it is a whole account token — not a prefix of a
    longer account (so `expenses:holiday` won't match `expenses:holiday:x`)."""
    pattern = r"(?<![\w:-])" + re.escape(old) + r"(?![\w:-])"
    return re.sub(pattern, new, text)


def _rename_in_transactions(old: str, new: str) -> int:
    config = load_app_config()
    changed_total = 0
    txn_dir = config.paths.transactions_dir
    if not txn_dir.exists():
        return 0
    for bank_dir in sorted(txn_dir.iterdir()):
        if not bank_dir.is_dir() or bank_dir.name.startswith("."):
            continue
        bank = bank_dir.name
        records = load_bank_transactions(bank)
        touched = False
        for record in records:
            record_changed = False
            if record.category == old:
                record.category = new
                record_changed = True
            for split in record.splits:
                if split.account == old:
                    split.account = new
                    record_changed = True
            if record_changed:
                record.updated_at = utc_now_iso()
                changed_total += 1
                touched = True
        if touched:
            replace_transactions(bank, records)
            build_bank_journal(bank)
    return changed_total


def _rename_in_taxonomy(path: Path, old: str, new: str) -> bool:
    if not path.exists():
        return False
    data = yaml.safe_load(path.read_text()) or {}
    cats = data.get("categories", []) or []
    if old not in cats:
        return False
    updated = sorted({new if c == old else c for c in cats})
    data["categories"] = updated
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return True


def rename_category(old: str, new: str) -> dict:
    if old == new or not old or not new:
        raise ValueError("old and new categories must differ and be non-empty")

    config = load_app_config()
    paths = config.paths
    txn_changed = _rename_in_transactions(old, new)

    files_changed: list[str] = []
    if _rename_in_taxonomy(paths.categories_config, old, new):
        files_changed.append(paths.categories_config.name)

    text_targets = [
        paths.accounts_config,
        paths.rules_config,
        paths.budget_groups_config,
        paths.manual_journal,
        paths.main_journal,
        *sorted(paths.journal_dir.glob("budget-*.journal")),
    ]
    for target in text_targets:
        if not target.exists():
            continue
        text = target.read_text()
        replaced = replace_account_token(text, old, new)
        if replaced != text:
            target.write_text(replaced)
            files_changed.append(target.name)

    return {"old": old, "new": new, "transactions": txn_changed, "files": files_changed}
