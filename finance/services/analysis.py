"""Thin service layer: load canonical transactions and run an analysis."""

from __future__ import annotations

from finance.analysis.cashflow import MonthCashflow, monthly_cashflow
from finance.analysis.recurring import Recurring, detect_recurring
from finance.analysis.trends import CategoryTrend, category_trends
from finance.services.transactions import load_all_transactions, load_bank_transactions


def _records(bank: str | None):
    return load_bank_transactions(bank) if bank else load_all_transactions()


def recurring(bank: str | None = None, *, min_occurrences: int = 3) -> list[Recurring]:
    return detect_recurring(_records(bank), min_occurrences=min_occurrences)


def cashflow(bank: str | None = None, *, months: int | None = None) -> list[MonthCashflow]:
    return monthly_cashflow(_records(bank), months=months)


def trends(bank: str | None = None, *, months: int = 6, depth: int | None = 2) -> tuple[list[CategoryTrend], list[str]]:
    return category_trends(_records(bank), months=months, depth=depth)
