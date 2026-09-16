"""Shared helpers: expand a record into category postings and bucket by month."""

from __future__ import annotations

from decimal import Decimal

from finance.models.transaction import TransactionRecord


def month_key(date: str) -> str:
    return date[:7]  # YYYY-MM


def is_expense(account: str) -> bool:
    return account.startswith("expenses:")


def is_income(account: str) -> bool:
    return account.startswith("income:")


def category_postings(record: TransactionRecord) -> list[tuple[str, Decimal]]:
    """(category account, positive magnitude) for a record, expanding splits so
    every rand is counted once against exactly one category."""
    if record.splits:
        return [(split.account, abs(Decimal(split.amount))) for split in record.splits]
    return [(record.category, abs(Decimal(record.amount)))]


def rollup(account: str, depth: int | None) -> str:
    """Collapse an account to a given colon-depth (e.g. depth 2: expenses:food)."""
    if not depth:
        return account
    return ":".join(account.split(":")[:depth])
