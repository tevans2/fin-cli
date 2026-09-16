"""Monthly cash flow: income, spend, net, and savings rate."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from finance.analysis.postings import category_postings, is_expense, is_income, month_key
from finance.models.transaction import TransactionRecord


@dataclass
class MonthCashflow:
    month: str
    income: Decimal
    spend: Decimal
    net: Decimal
    savings_rate: float | None   # net / income, None when there was no income


def monthly_cashflow(records: list[TransactionRecord], *, months: int | None = None) -> list[MonthCashflow]:
    income: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    spend: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    for record in records:
        bucket = month_key(record.date)
        for account, magnitude in category_postings(record):
            if is_expense(account):
                spend[bucket] += magnitude
            elif is_income(account):
                income[bucket] += magnitude

    all_months = sorted(set(income) | set(spend))
    if months:
        all_months = all_months[-months:]

    result: list[MonthCashflow] = []
    for month in all_months:
        inc = income.get(month, Decimal(0))
        spent = spend.get(month, Decimal(0))
        net = inc - spent
        rate = float(net / inc) if inc > 0 else None
        result.append(MonthCashflow(month=month, income=inc, spend=spent, net=net, savings_rate=rate))
    return result
