from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from finance.statements.model import StatementFormatError, StatementRow
from finance.statements.profile import StatementProfile


def normalize_header(value: str) -> str:
    return " ".join((value or "").strip().lower().replace("_", " ").split())


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
        raise StatementFormatError(f"Invalid number: {value!r}") from exc


def _parse_date(value: str, formats: list[str]) -> str:
    text = (value or "").strip()
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise StatementFormatError(f"Unsupported date format: {value!r}")


def _find_header(lines: list[str], profile: StatementProfile) -> int:
    """Index of the header row, skipping any preamble."""
    if not profile.header_marker:
        return 0
    wanted = {normalize_header(col) for col in profile.header_marker}
    for index, line in enumerate(lines):
        cells = {normalize_header(cell) for cell in next(csv.reader([line], delimiter=profile.delimiter))}
        if wanted <= cells:
            return index
    raise StatementFormatError(
        f"Could not find a header row containing: {', '.join(profile.header_marker)}"
    )


def resolve_columns(fieldnames: list[str], profile: StatementProfile) -> dict[str, str]:
    """Map each canonical field to an actual header, by normalized alias match."""
    normalized = {normalize_header(name): name for name in fieldnames if name is not None}
    mapping: dict[str, str] = {}
    for field_name, aliases in profile.columns.items():
        for alias in aliases:
            key = normalize_header(alias)
            if key in normalized:
                mapping[field_name] = normalized[key]
                break
    if "date" not in mapping:
        raise StatementFormatError(f"Could not find a date column (tried: {profile.columns.get('date', [])})")
    if "description" not in mapping:
        raise StatementFormatError("Could not find a description column")
    if "amount" not in mapping and not ("debit" in mapping and "credit" in mapping):
        raise StatementFormatError("Need either an amount column or both a debit and a credit column")
    return mapping


def _row_amount(raw: dict[str, str], mapping: dict[str, str], line_number: int) -> str:
    if "amount" in mapping:
        text = _clean_number(raw.get(mapping["amount"]))
        if not text:
            raise StatementFormatError(f"Line {line_number}: blank amount")
        return f"{_decimal(text):.2f}"
    debit = _decimal(raw.get(mapping["debit"]))
    credit = _decimal(raw.get(mapping["credit"]))
    if debit and credit:
        raise StatementFormatError(f"Line {line_number}: row has both a debit and a credit")
    if not debit and not credit:
        raise StatementFormatError(f"Line {line_number}: row has neither a debit nor a credit")
    return f"{credit - debit:.2f}"


def _account_name(lines: list[str], header_index: int) -> str | None:
    for line in lines[:header_index]:
        if ":" in line:
            return line.split(":", 1)[1].strip().rstrip(",") or None
    return None


def parse_csv(path: Path, profile: StatementProfile) -> tuple[list[StatementRow], str | None]:
    """Parse a CSV statement into chronologically ordered rows + account name."""
    text = Path(path).read_text(encoding=profile.encoding)
    lines = text.splitlines()
    if not lines:
        raise StatementFormatError("Statement file is empty")

    header_index = _find_header(lines, profile)
    account_name = _account_name(lines, header_index) if profile.account_name_from_preamble else None

    reader = csv.DictReader(lines[header_index:], delimiter=profile.delimiter)
    if not reader.fieldnames:
        raise StatementFormatError("CSV has no header row")
    mapping = resolve_columns(list(reader.fieldnames), profile)

    rows: list[StatementRow] = []
    for offset, raw in enumerate(reader):
        line_number = header_index + 2 + offset
        if not any((value or "").strip() for value in raw.values()):
            continue
        description = " ".join((raw.get(mapping["description"]) or "").split())
        if not description:
            raise StatementFormatError(f"Line {line_number}: blank description")
        balance = None
        if "balance" in mapping:
            balance_text = _clean_number(raw.get(mapping["balance"]))
            balance = f"{_decimal(balance_text):.2f}" if balance_text else None
        reference = None
        if "reference" in mapping:
            reference = (raw.get(mapping["reference"]) or "").strip() or None
        action_date = None
        if "action_date" in mapping:
            action_date = _parse_date(raw.get(mapping["action_date"], ""), profile.date_formats)
        rows.append(
            StatementRow(
                date=_parse_date(raw.get(mapping["date"], ""), profile.date_formats),
                description=description,
                amount=_row_amount(raw, mapping, line_number),
                balance=balance,
                reference=reference,
                action_date=action_date,
                line_number=line_number,
                raw=dict(raw),
            )
        )

    if profile.order == "newest_first":
        rows.reverse()
    return rows, account_name
