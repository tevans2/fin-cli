"""Reconcile the ledger against the banks — the standing accuracy test.

For each account, the newest imported row carries the bank's own running balance
in ``provider_metadata.balance``. ``fin verify`` compares that to the balance the
ledger computes as of the same date. Agreement means every transaction is present
and correct; a difference points at drift to investigate.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from finance.models.transaction import TransactionRecord
from finance.services import hledger
from finance.services.transactions import load_all_transactions


def _statement_balance(record: TransactionRecord) -> str | None:
    balance = (record.provider_metadata or {}).get("balance")
    return balance if balance not in (None, "") else None


def _statement_line(record: TransactionRecord) -> int:
    try:
        return int((record.provider_metadata or {}).get("statement_line") or 0)
    except (TypeError, ValueError):
        return 0


def _terminal_record(day_records: list[TransactionRecord]) -> TransactionRecord:
    """The last transaction of a day, so its balance is the end-of-day balance.

    Compares to the ledger, which is date-granular, so we must not pick a
    mid-day row. Order is reconstructed from the running balance itself: record
    ``s`` follows ``r`` when ``s.balance - s.amount == r.balance``, so the
    terminal record is the one that is nobody's predecessor.
    """
    if len(day_records) == 1:
        return day_records[0]
    balances = {id(r): Decimal(_statement_balance(r)) for r in day_records}  # type: ignore[arg-type]

    def has_successor(r: TransactionRecord) -> bool:
        rb = balances[id(r)]
        return any(s is not r and balances[id(s)] - Decimal(s.amount) == rb for s in day_records)

    terminals = [r for r in day_records if not has_successor(r)]
    if len(terminals) == 1:
        return terminals[0]
    # ambiguous chain: best effort — highest statement line, then highest balance
    return max(day_records, key=lambda r: (_statement_line(r), balances[id(r)]))


def latest_statement_balances(records: list[TransactionRecord]) -> dict[tuple[str, str], dict]:
    """End-of-day bank balance on the latest dated statement, per account."""
    by_account: dict[tuple[str, str], list[TransactionRecord]] = defaultdict(list)
    for record in records:
        if _statement_balance(record) is not None:
            by_account[(record.institution, record.source_account)].append(record)

    best: dict[tuple[str, str], dict] = {}
    for key, account_records in by_account.items():
        max_date = max(r.date for r in account_records)
        day = [r for r in account_records if r.date == max_date]
        terminal = _terminal_record(day)
        best[key] = {
            "date": max_date,
            "balance": _statement_balance(terminal),
            "ledger_account": terminal.ledger_account,
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
