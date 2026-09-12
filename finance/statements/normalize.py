"""Shared value-cleaning helpers for statement parsing (CSV and PDF)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from finance.statements.model import StatementFormatError


def normalize_header(value: str) -> str:
    return " ".join((value or "").strip().lower().replace("_", " ").split())


def clean_number(value: str | None) -> str:
    text = (value or "").strip().replace("R", "").replace(",", "").replace(" ", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    return text


def to_decimal(value: str | None) -> Decimal:
    text = clean_number(value)
    if not text:
        return Decimal(0)
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise StatementFormatError(f"Invalid number: {value!r}") from exc


def parse_date(value: str, formats: list[str]) -> str:
    text = (value or "").strip()
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise StatementFormatError(f"Unsupported date format: {value!r}")
