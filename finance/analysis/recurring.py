"""Detect recurring merchants (subscriptions, regular payments).

Groups spend by merchant key, looks at the gaps between charges, and reports
merchants whose cadence is regular (weekly … yearly). Amount stability and an
active/lapsed flag help spot new, changed, or cancelled subscriptions.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finance.classify.normalize import merchant_key
from finance.models.transaction import TransactionRecord

# name, ideal interval in days, tolerance
_CADENCES = [
    ("weekly", 7, 2),
    ("fortnightly", 14, 3),
    ("monthly", 30, 6),
    ("quarterly", 91, 12),
    ("yearly", 365, 25),
]

_NON_SPEND_PREFIXES = ("income:", "assets:", "liabilities:", "equity:")


@dataclass
class Recurring:
    merchant: str
    cadence: str
    interval_days: float
    typical_amount: Decimal
    amount_stable: bool
    occurrences: int
    first: str
    last: str
    active: bool


def _cadence(median_interval: float) -> str:
    for name, ideal, tol in _CADENCES:
        if abs(median_interval - ideal) <= tol:
            return name
    return "irregular"


def detect_recurring(
    records: list[TransactionRecord],
    *,
    min_occurrences: int = 3,
    as_of: str | None = None,
) -> list[Recurring]:
    groups: dict[str, list[TransactionRecord]] = defaultdict(list)
    for record in records:
        if record.category.startswith(_NON_SPEND_PREFIXES):
            continue
        key = merchant_key(record.description)
        if key:
            groups[key].append(record)

    horizon = as_of or (max((r.date for r in records), default=None))
    results: list[Recurring] = []
    for key, items in groups.items():
        if len(items) < min_occurrences:
            continue
        items.sort(key=lambda r: r.date)
        dates = [date.fromisoformat(r.date) for r in items]
        intervals = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
        intervals = [d for d in intervals if d > 0]
        if not intervals:
            continue
        median_interval = float(statistics.median(intervals))
        cadence = _cadence(median_interval)
        if cadence == "irregular":
            continue

        amounts = [abs(Decimal(r.amount)) for r in items]
        typical = Decimal(str(statistics.median(amounts)))
        floats = [float(a) for a in amounts]
        mean = statistics.fmean(floats)
        stdev = statistics.pstdev(floats) if len(floats) > 1 else 0.0
        amount_stable = bool(mean) and (stdev / mean) < 0.25

        active = True
        if horizon:
            gap = (date.fromisoformat(horizon) - dates[-1]).days
            active = gap <= median_interval * 1.5

        display = next((r.merchant or r.alias for r in items if (r.merchant or r.alias)), None) or key.title()
        results.append(
            Recurring(
                merchant=display,
                cadence=cadence,
                interval_days=median_interval,
                typical_amount=typical,
                amount_stable=amount_stable,
                occurrences=len(items),
                first=items[0].date,
                last=items[-1].date,
                active=active,
            )
        )

    results.sort(key=lambda r: (not r.active, -r.occurrences, r.merchant))
    return results
