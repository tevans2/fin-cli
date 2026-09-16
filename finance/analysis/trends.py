"""Category spend trends: this month vs the trailing average, biggest movers first."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from finance.analysis.postings import category_postings, is_expense, month_key, rollup
from finance.models.transaction import TransactionRecord


@dataclass
class CategoryTrend:
    category: str
    latest: Decimal
    previous_avg: Decimal
    change: Decimal                       # latest - previous_avg
    monthly: dict[str, Decimal] = field(default_factory=dict)

    @property
    def change_pct(self) -> float | None:
        return float(self.change / self.previous_avg) if self.previous_avg else None


def category_trends(
    records: list[TransactionRecord],
    *,
    months: int = 6,
    depth: int | None = 2,
) -> tuple[list[CategoryTrend], list[str]]:
    """Return (trends sorted by biggest absolute change, the month columns)."""
    by_category: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: Decimal(0)))
    for record in records:
        bucket = month_key(record.date)
        for account, magnitude in category_postings(record):
            if is_expense(account):
                by_category[rollup(account, depth)][bucket] += magnitude

    all_months = sorted({m for months_map in by_category.values() for m in months_map})[-months:]
    if not all_months:
        return [], []
    latest, previous = all_months[-1], all_months[:-1]

    trends: list[CategoryTrend] = []
    for category, months_map in by_category.items():
        latest_amt = months_map.get(latest, Decimal(0))
        prev_amts = [months_map.get(m, Decimal(0)) for m in previous]
        prev_avg = sum(prev_amts, Decimal(0)) / len(prev_amts) if prev_amts else Decimal(0)
        trends.append(
            CategoryTrend(
                category=category,
                latest=latest_amt,
                previous_avg=prev_avg,
                change=latest_amt - prev_avg,
                monthly={m: months_map.get(m, Decimal(0)) for m in all_months},
            )
        )

    trends.sort(key=lambda t: -abs(t.change))
    return trends, all_months
