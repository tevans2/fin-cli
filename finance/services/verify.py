"""Reconcile the ledger against the banks — the standing accuracy test.

For each account, the newest imported row carries the bank's own running balance
in ``provider_metadata.balance``. ``fin verify`` compares that to the balance the
ledger computes as of the same date. Agreement means every transaction is present
and correct; a difference points at drift to investigate.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from finance.models.transaction import TransactionRecord
from finance.services import hledger
from finance.services.transactions import load_all_transactions


def _statement_balance(record: TransactionRecord) -> str | None:
    balance = (record.provider_metadata or {}).get("balance")
    return balance if balance not in (None, "") else None


def _rank(record: TransactionRecord) -> tuple:
    try:
        line = int((record.provider_metadata or {}).get("statement_line") or 0)
    except (TypeError, ValueError):
        line = 0
    return (record.date, line, record.id)


def latest_statement_balances(records: list[TransactionRecord]) -> dict[tuple[str, str], dict]:
    """Newest known bank balance per (institution, source_account)."""
    best: dict[tuple[str, str], dict] = {}
    for record in records:
        balance = _statement_balance(record)
        if balance is None:
            continue
        key = (record.institution, record.source_account)
        rank = _rank(record)
        current = best.get(key)
        if current is None or rank > current["rank"]:
            best[key] = {
                "date": record.date,
                "balance": balance,
                "ledger_account": record.ledger_account,
                "rank": rank,
            }
    return best


def parse_hledger_amount(text: str) -> Decimal | None:
    match = re.search(r"-?\d+(?:\.\d+)?", (text or "").replace(",", ""))
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def ledger_balance(account: str, end_date: str) -> Decimal | None:
    """Ledger balance of an account up to and including ``end_date``."""
    end_exclusive = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    rows = hledger.read_csv(["balance", account, "-e", end_exclusive])
    for row in rows:
        if (row.get("account") or "").strip().lower().rstrip(":") == "total":
            return parse_hledger_amount(row.get("balance", ""))
    return None


def verify_accounts() -> list[dict]:
    """Compare each account's latest statement balance to the ledger."""
    balances = latest_statement_balances(load_all_transactions())
    results: list[dict] = []
    for (institution, source_account), info in sorted(balances.items()):
        statement = Decimal(info["balance"])
        ledger = ledger_balance(info["ledger_account"], info["date"])
        diff = None if ledger is None else statement - ledger
        results.append(
            {
                "institution": institution,
                "source_account": source_account,
                "ledger_account": info["ledger_account"],
                "as_of": info["date"],
                "statement_balance": statement,
                "ledger_balance": ledger,
                "difference": diff,
                "ok": diff == 0,
            }
        )
    return results
