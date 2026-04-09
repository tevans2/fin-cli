from __future__ import annotations

import re
from pathlib import Path

import yaml

from finance.config import load_app_config
from finance.models.state import BankSyncState
from finance.models.transaction import TransactionRecord, utc_now_iso
from finance.services.journal import build_bank_journal
from finance.storage.accounts_store import AccountsStore
from finance.storage.jsonl_store import JsonlTransactionStore
from finance.storage.state_store import SyncStateStore


HEADER_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<status>[*!])\s+(?P<desc>.*?)(?:\s+;\s*txn_id:\s*(?P<txn_id>\S+))?\s*$")
POSTING_RE = re.compile(r"^\s+(?P<account>\S+)\s+(?P<amount>.+?)\s*$")
AMOUNT_RE = re.compile(r"^(?P<commodity>[^\d\-+]*)(?P<number>[\-+]?\d[\d,]*\.\d+)$")


def _split_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _parse_amount(raw: str) -> tuple[str, str]:
    value = raw.strip()
    match = AMOUNT_RE.match(value)
    if not match:
        raise ValueError(f"Unsupported amount format: {raw}")
    commodity = match.group("commodity").strip()
    number = match.group("number").replace(",", "")
    currency = {"R": "ZAR", "$": "USD", "": "ZAR"}.get(commodity, commodity or "ZAR")
    return currency, number


def _infer_source_account_name(ledger_account: str) -> str:
    if ":" in ledger_account:
        return ledger_account.split(":")[-1]
    return ledger_account


def parse_v1_incoming_journal(path: Path) -> list[TransactionRecord]:
    text = path.read_text()
    records: list[TransactionRecord] = []

    for block in _split_blocks(text):
        header_line = next((line for line in block if not line.lstrip().startswith(";")), None)
        if not header_line:
            continue
        header_match = HEADER_RE.match(header_line)
        if not header_match:
            continue

        posting_lines = [line for line in block[1:] if line.strip() and not line.lstrip().startswith(";")]
        postings = []
        for line in posting_lines:
            match = POSTING_RE.match(line)
            if match:
                postings.append((match.group("account"), match.group("amount")))
        if len(postings) < 2:
            continue

        ledger_account, source_amount_raw = postings[0]
        category_account, _ = postings[1]
        currency, amount = _parse_amount(source_amount_raw)

        txn_id = header_match.group("txn_id") or f"migrated:{header_match.group('date')}:{header_match.group('desc')}:{amount}"
        status = "cleared" if header_match.group("status") == "*" else "pending"
        description = header_match.group("desc").strip()

        records.append(
            TransactionRecord(
                id=txn_id,
                institution="investec",
                source_account=_infer_source_account_name(ledger_account),
                ledger_account=ledger_account,
                date=header_match.group("date"),
                description=description,
                amount=amount,
                currency=currency,
                category=category_account,
                category_source="migration:v1",
                status=status,
                imported_at=utc_now_iso(),
                payee=description,
                notes=None,
                tags=[],
                updated_at=None,
                source_hash=None,
                provider_metadata={"migrated_from": str(path)},
            )
        )

    return records


def extract_v1_account_declarations(source_root: Path) -> list[str]:
    main_path = source_root / "journal" / "main.journal"
    if not main_path.exists():
        return []
    accounts: list[str] = []
    for raw_line in main_path.read_text().splitlines():
        line = raw_line.strip()
        if line.startswith("account "):
            account = line[len("account "):].strip()
            if account:
                accounts.append(account)
    return accounts


def combine_manual_journals(source_root: Path) -> str:
    parts: list[str] = []
    file_order = [
        ("opening-balances", source_root / "journal" / "opening-balances.journal"),
        ("investments", source_root / "journal" / "investments.journal"),
        ("manual", source_root / "journal" / "manual.journal"),
    ]
    for label, path in file_order:
        if path.exists():
            content = path.read_text().strip()
            if content:
                parts.append(f"; --- migrated from v1/{label} ---\n{content}\n")
    return "\n".join(parts).rstrip() + "\n" if parts else "; Manual finance entries\n"


def parse_v1_rules_file(path: Path) -> list[dict]:
    if not path.exists():
        return []

    rules: list[dict] = []
    current_pattern: str | None = None
    priority = 100

    for raw_line in path.read_text().splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if current_pattern and stripped.startswith("account2 "):
            category = stripped[len("account2 "):].strip()
            rule_name = re.sub(r"[^a-z0-9]+", "-", current_pattern.lower()).strip("-") or f"rule-{priority}"
            match_data: dict[str, str] = {}

            if current_pattern.startswith("%amount"):
                amount_expr = current_pattern[len("%amount"):].strip()
                if amount_expr == "^[0-9]":
                    match_data["amount_gt"] = "0"
                elif amount_expr.startswith("^-"):
                    match_data["amount_lt"] = "0"
            else:
                match_data["description_regex"] = current_pattern

            if not match_data:
                if category.startswith("expenses:"):
                    match_data["amount_lt"] = "0"
                elif category.startswith("income:"):
                    match_data["amount_gt"] = "0"
                else:
                    match_data["description_regex"] = current_pattern

            rules.append(
                {
                    "name": f"migrated-{rule_name}",
                    "category": category,
                    "priority": priority,
                    "enabled": True,
                    "notes": f"Migrated from v1 CSV rules: {current_pattern}",
                    "match": match_data,
                }
            )
            priority += 10
            current_pattern = None
            continue

        if stripped.startswith(("fields ", "skip ", "currency ", "account1 ", "comment ", "account2 ", "status ")):
            continue

        if stripped.startswith("if "):
            current_pattern = stripped[3:].strip()
            continue

    return rules


def write_aliases_yaml(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with open(path, "w") as f:
            yaml.safe_dump({"aliases": []}, f, sort_keys=False)


def write_rules_yaml(path: Path, migrated_rules: list[dict]) -> None:
    data = {
        "rules": [
            *migrated_rules,
            {
                "name": "default-expense-unknown",
                "category": "expenses:unknown",
                "priority": 1000,
                "enabled": True,
                "notes": "Fallback expense category",
                "match": {"amount_lt": "0"},
            },
            {
                "name": "default-income-unknown",
                "category": "income:unknown",
                "priority": 1000,
                "enabled": True,
                "notes": "Fallback income category",
                "match": {"amount_gt": "0"},
            },
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)



def migrate_v1(source_root: Path, overwrite_manual: bool = True, overwrite_rules: bool = True) -> dict:
    config = load_app_config()

    incoming_path = source_root / "journal" / "incoming.journal"
    if not incoming_path.exists():
        raise FileNotFoundError(f"V1 incoming journal not found: {incoming_path}")

    records = parse_v1_incoming_journal(incoming_path)
    tx_store = JsonlTransactionStore(config.paths.transactions_dir)

    by_year: dict[int, list[TransactionRecord]] = {}
    for record in records:
        by_year.setdefault(int(record.date[:4]), []).append(record)

    inserted = 0
    updated = 0
    for year, rows in by_year.items():
        file_path = config.paths.transaction_file("investec", year)
        i, u = tx_store.merge_file(file_path, rows)
        inserted += i
        updated += u

    if overwrite_manual:
        config.paths.manual_journal.write_text(combine_manual_journals(source_root))

    write_aliases_yaml(config.paths.aliases_config)
    AccountsStore(config.paths.accounts_config).save(extract_v1_account_declarations(source_root))

    migrated_rules = []
    rules_path = source_root / "imports" / "investec" / "rules" / "investec.csv.rules"
    if overwrite_rules:
        migrated_rules = parse_v1_rules_file(rules_path)
        write_rules_yaml(config.paths.rules_config, migrated_rules)

    last_fetch_path = source_root / "imports" / "investec" / "state" / "last_fetch.txt"
    state_store = SyncStateStore(config.paths.sync_state)
    state = state_store.load()
    state.banks["investec"] = BankSyncState(
        last_successful_sync_date=last_fetch_path.read_text().strip() if last_fetch_path.exists() else None,
        cursor=None,
    )
    state_store.save(state)

    journal_result = build_bank_journal("investec")

    return {
        "source": str(source_root),
        "records": len(records),
        "inserted": inserted,
        "updated": updated,
        "years": sorted(by_year.keys()),
        "manual_journal": str(config.paths.manual_journal),
        "generated_journal": journal_result["output"],
        "rules_migrated": len(migrated_rules),
        "rules_config": str(config.paths.rules_config),
    }
