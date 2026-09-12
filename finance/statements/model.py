from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


class StatementFormatError(ValueError):
    """The statement file could not be parsed against its profile."""


class BalanceChainError(ValueError):
    """The running-balance column does not agree with the debits/credits."""


@dataclass
class StatementRow:
    """One normalized statement line, independent of source format.

    ``amount`` is signed (negative = money out) and formatted to 2 decimals.
    ``balance`` is the running account balance after this row, when the
    statement provides one. ``action_date`` is an optional secondary date
    (e.g. Investec's transaction date vs posting date).
    """

    date: str
    description: str
    amount: str
    balance: str | None = None
    reference: str | None = None
    action_date: str | None = None
    line_number: int | None = None
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def amount_decimal(self) -> Decimal:
        return Decimal(self.amount)

    @property
    def balance_decimal(self) -> Decimal | None:
        return Decimal(self.balance) if self.balance is not None else None


@dataclass
class StatementSummary:
    rows: int
    date_range: dict[str, str] | None
    opening_balance: str | None
    closing_balance: str | None
    total_debits: str
    total_credits: str
    balance_chain_verified: bool
    account_name: str | None = None
