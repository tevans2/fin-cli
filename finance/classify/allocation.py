"""Category allocations: split a transaction so every cent is in exactly one category.

A transaction's amount is partitioned into one or more allocations. A single
category is just one allocation covering the whole magnitude; a split is several.
The invariant is strict — allocations must sum to the transaction's magnitude
exactly (Decimal, to the cent) and each must be a positive amount — so no cent is
double-counted or lost.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class AllocationError(ValueError):
    pass


@dataclass
class Allocation:
    account: str            # the category account, e.g. expenses:food:groceries
    amount: str             # positive magnitude, formatted to 2 decimals
    notes: str | None = None

    @property
    def amount_decimal(self) -> Decimal:
        return Decimal(self.amount)


def magnitude(transaction_amount: str | Decimal) -> Decimal:
    return abs(Decimal(str(transaction_amount)))


def validate_allocations(allocations: list[Allocation], transaction_amount: str | Decimal) -> None:
    """Raise unless the allocations partition the transaction magnitude exactly."""
    if not allocations:
        raise AllocationError("no allocations")
    total = Decimal(0)
    for alloc in allocations:
        value = alloc.amount_decimal
        if value <= 0:
            raise AllocationError(f"allocation for {alloc.account!r} must be positive, got {alloc.amount}")
        if not alloc.account:
            raise AllocationError("allocation is missing a category account")
        total += value
    expected = magnitude(transaction_amount)
    if total != expected:
        raise AllocationError(f"allocations sum to {total}, expected {expected} (every cent must be in one category)")


def to_splits(allocations: list[Allocation]) -> list:
    """Convert allocations to TransactionSplit objects for storage on a record.

    Only meaningful for a real split (more than one allocation); a single
    allocation is stored as the record's plain category instead.
    """
    from finance.models.transaction import TransactionSplit

    return [TransactionSplit(account=a.account, amount=a.amount, notes=a.notes) for a in allocations]


def even_split(accounts: list[str], transaction_amount: str | Decimal) -> list[Allocation]:
    """Split a magnitude across accounts evenly, assigning the rounding remainder
    to the first account so the parts still sum exactly."""
    if not accounts:
        raise AllocationError("no accounts to split across")
    total = magnitude(transaction_amount)
    per = (total / len(accounts)).quantize(Decimal("0.01"))
    parts = [per] * len(accounts)
    parts[0] += total - sum(parts)  # absorb the remainder
    return [Allocation(account=acct, amount=f"{part:.2f}") for acct, part in zip(accounts, parts, strict=True)]
