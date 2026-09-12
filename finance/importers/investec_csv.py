"""Importer for Investec's downloadable transaction CSV.

The export looks like this — an account-name preamble line, then the real
header, then newest-first rows with separate debit/credit columns and a
running balance:

    Account Name:Mr TAT Evans  10013116355,,,,,
    Transaction Date,Posting Date,Description,Debits,Credits,Balance
    2025/12/31,2026/01/01,YOCO   *LIQUID RAINBOW CAPE TOWN ZA,165,,19636.56

Records are dated by *posting* date so they line up with what the Investec
API importer stores (``record_date_mode="posting"``); the transaction date is
kept in ``provider_metadata`` as ``action_date``.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

REQUIRED_COLUMNS = ["Transaction Date", "Posting Date", "Description", "Debits", "Credits", "Balance"]


@dataclass
class InvestecCsvRow:
    date: str
    action_date: str
    description: str
    amount: str
    balance: str
    line_number: int
    raw: dict[str, str]


class InvestecCsvFormatError(ValueError):
    pass


class BalanceChainError(ValueError):
    """The running-balance column does not agree with the debits/credits."""


def _clean_number(value: str | None) -> str:
    text = (value or "").strip().replace("R", "").replace(",", "").replace(" ", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    return text


def _decimal(value: str | None) -> Decimal:
    text = _clean_number(value)
    if not text:
        return Decimal(0)
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise InvestecCsvFormatError(f"Invalid number: {value!r}") from exc


def _parse_date(value: str) -> str:
    text = (value or "").strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise InvestecCsvFormatError(f"Unsupported date format: {value!r}")


def _find_header(lines: list[str]) -> int:
    """Index of the real header row, skipping the account-name preamble."""
    for index, line in enumerate(lines[:10]):
        cells = [cell.strip() for cell in next(csv.reader([line]))]
        if all(column in cells for column in REQUIRED_COLUMNS):
            return index
    raise InvestecCsvFormatError(
        f"Could not find a header row containing {', '.join(REQUIRED_COLUMNS)}"
    )


def verify_balance_chain(rows: list[InvestecCsvRow]) -> list[dict]:
    """Check every row's balance against the previous row's balance + amount.

    ``rows`` must be in chronological order. Returns a list of breaks; an
    empty list means the statement is internally consistent, which also
    proves no row was duplicated or dropped by the export.
    """
    breaks: list[dict] = []
    for previous, current in zip(rows, rows[1:]):
        expected = Decimal(previous.balance) + Decimal(current.amount)
        actual = Decimal(current.balance)
        if expected != actual:
            breaks.append(
                {
                    "line": current.line_number,
                    "date": current.date,
                    "description": current.description,
                    "expected_balance": f"{expected:.2f}",
                    "actual_balance": f"{actual:.2f}",
                    "difference": f"{actual - expected:.2f}",
                }
            )
    return breaks


def opening_balance(rows: list[InvestecCsvRow]) -> str:
    """Account balance immediately before the first (chronological) row."""
    if not rows:
        return "0.00"
    return f"{Decimal(rows[0].balance) - Decimal(rows[0].amount):.2f}"


def parse_investec_csv(csv_path: Path) -> tuple[list[InvestecCsvRow], dict]:
    """Parse the export into chronologically ordered rows plus a summary."""
    text = Path(csv_path).read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    header_index = _find_header(lines)
    account_name = lines[0].split(":", 1)[1].strip().rstrip(",") if header_index and ":" in lines[0] else None

    reader = csv.DictReader(lines[header_index:])
    rows: list[InvestecCsvRow] = []
    for offset, raw_row in enumerate(reader):
        line_number = header_index + 2 + offset
        if not any((value or "").strip() for value in raw_row.values()):
            continue
        debit = _decimal(raw_row.get("Debits"))
        credit = _decimal(raw_row.get("Credits"))
        if debit and credit:
            raise InvestecCsvFormatError(f"Line {line_number}: row has both a debit and a credit")
        if not debit and not credit:
            raise InvestecCsvFormatError(f"Line {line_number}: row has neither a debit nor a credit")
        description = " ".join((raw_row.get("Description") or "").split())
        if not description:
            raise InvestecCsvFormatError(f"Line {line_number}: blank description")
        rows.append(
            InvestecCsvRow(
                date=_parse_date(raw_row.get("Posting Date", "")),
                action_date=_parse_date(raw_row.get("Transaction Date", "")),
                description=description,
                amount=f"{credit - debit:.2f}",
                balance=f"{_decimal(raw_row.get('Balance')):.2f}",
                line_number=line_number,
                raw=dict(raw_row),
            )
        )

    # The export is newest-first; the balance chain reads forwards in time.
    rows.reverse()
    summary = {
        "account_name": account_name,
        "rows": len(rows),
        "date_range": {"start": rows[0].date, "end": rows[-1].date} if rows else None,
        "opening_balance": opening_balance(rows),
        "closing_balance": rows[-1].balance if rows else "0.00",
        "total_debits": f"{sum(Decimal(r.amount) for r in rows if Decimal(r.amount) < 0):.2f}",
        "total_credits": f"{sum(Decimal(r.amount) for r in rows if Decimal(r.amount) > 0):.2f}",
    }
    return rows, summary


def build_record_id(row: InvestecCsvRow, account: str, occurrence: int = 0) -> str:
    """Stable id for a statement row.

    The running balance is part of the key, so the many genuinely repeated
    rows (same day, same merchant, same amount) still get distinct ids.
    ``occurrence`` disambiguates the theoretical case where even the balance
    repeats.
    """
    stable = "|".join(
        [row.date, row.action_date, row.description, row.amount, row.balance, account, str(occurrence)]
    )
    return "investec-csv:" + hashlib.sha256(stable.encode()).hexdigest()[:16]
