from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


HEADER_ALIASES = {
    "date": ["date", "transaction date", "posting date", "value date"],
    "description": ["description", "details", "transaction", "narration", "merchant"],
    "amount": ["amount", "transaction amount", "signed amount"],
    "debit": ["debit", "withdrawal", "money out"],
    "credit": ["credit", "deposit", "money in"],
    "balance": ["balance", "running balance", "available balance"],
    "reference": ["reference", "ref", "transaction id", "id"],
}

DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
]


@dataclass
class TymeCsvRow:
    date: str
    description: str
    amount: str
    balance: str | None
    reference: str | None
    raw: dict[str, str]


class TymeCsvFormatError(ValueError):
    pass


def _normalize_header(value: str) -> str:
    return " ".join((value or "").strip().lower().replace("_", " ").split())


def _find_column(fieldnames: list[str], explicit: str | None, aliases: list[str]) -> str | None:
    if explicit:
        for name in fieldnames:
            if name == explicit:
                return name
        raise TymeCsvFormatError(f"CSV column not found: {explicit}")
    normalized = {_normalize_header(name): name for name in fieldnames}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return None


def detect_mapping(fieldnames: list[str], overrides: dict[str, str | None] | None = None) -> dict[str, str | None]:
    overrides = overrides or {}
    mapping = {
        field: _find_column(fieldnames, overrides.get(field), aliases)
        for field, aliases in HEADER_ALIASES.items()
    }
    if not mapping["date"]:
        raise TymeCsvFormatError("Could not detect a date column")
    if not mapping["description"]:
        raise TymeCsvFormatError("Could not detect a description column")
    if not mapping["amount"] and not (mapping["debit"] and mapping["credit"]):
        raise TymeCsvFormatError("Need either an amount column or both debit and credit columns")
    return mapping


def _clean_number(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    text = text.replace("R", "").replace(",", "").replace(" ", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    return text


def _parse_amount(row: dict[str, str], mapping: dict[str, str | None]) -> str:
    amount_col = mapping.get("amount")
    if amount_col:
        raw = _clean_number(row.get(amount_col))
        if not raw:
            raise TymeCsvFormatError("Blank amount value")
        try:
            return f"{Decimal(raw):.2f}"
        except InvalidOperation as exc:
            raise TymeCsvFormatError(f"Invalid amount: {row.get(amount_col)!r}") from exc

    debit = Decimal(_clean_number(row.get(mapping["debit"])) or "0")
    credit = Decimal(_clean_number(row.get(mapping["credit"])) or "0")
    amount = credit - debit
    return f"{amount:.2f}"


def _parse_balance(row: dict[str, str], mapping: dict[str, str | None]) -> str | None:
    balance_col = mapping.get("balance")
    if not balance_col:
        return None
    raw = _clean_number(row.get(balance_col))
    if not raw:
        return None
    try:
        return f"{Decimal(raw):.2f}"
    except InvalidOperation:
        return None


def _parse_date(value: str) -> str:
    text = (value or "").strip()
    for fmt in DATE_FORMATS:
        try:
            from datetime import datetime

            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise TymeCsvFormatError(f"Unsupported date format: {value!r}")


def _build_id(date: str, description: str, amount: str, account: str, reference: str | None, balance: str | None) -> str:
    stable = "|".join([date, description.strip(), amount, account, reference or "", balance or ""])
    return "tyme:" + hashlib.sha256(stable.encode()).hexdigest()[:16]


def parse_tyme_csv(
    csv_path: Path,
    *,
    account: str = "checking",
    delimiter: str = ",",
    mapping_overrides: dict[str, str | None] | None = None,
) -> tuple[list[TymeCsvRow], dict[str, str | None]]:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if not reader.fieldnames:
            raise TymeCsvFormatError("CSV file has no header row")
        mapping = detect_mapping(list(reader.fieldnames), mapping_overrides)
        rows: list[TymeCsvRow] = []
        for raw_row in reader:
            if not any((value or "").strip() for value in raw_row.values()):
                continue
            date = _parse_date(raw_row.get(mapping["date"], ""))
            description = (raw_row.get(mapping["description"], "") or "").strip()
            if not description:
                raise TymeCsvFormatError(f"Blank description on {date}")
            amount = _parse_amount(raw_row, mapping)
            balance = _parse_balance(raw_row, mapping)
            reference = None
            if mapping.get("reference"):
                reference = (raw_row.get(mapping["reference"], "") or "").strip() or None
            rows.append(
                TymeCsvRow(
                    date=date,
                    description=description,
                    amount=amount,
                    balance=balance,
                    reference=reference,
                    raw=dict(raw_row),
                )
            )
    return rows, mapping


def build_tyme_record_id(row: TymeCsvRow, account: str) -> str:
    return _build_id(row.date, row.description, row.amount, account, row.reference, row.balance)
