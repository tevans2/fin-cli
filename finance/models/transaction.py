from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


VALID_STATUS = {"cleared", "pending"}


@dataclass
class TransactionRecord:
    id: str
    institution: str
    source_account: str
    ledger_account: str
    date: str
    description: str
    amount: str
    currency: str
    category: str
    category_source: str
    status: str
    imported_at: str
    payee: str | None = None
    alias: str | None = None
    notes: str | None = None
    tags: list[str] = field(default_factory=list)
    updated_at: str | None = None
    source_hash: str | None = None
    provider_metadata: dict[str, Any] | None = None

    def validate(self) -> None:
        required = {
            "id": self.id,
            "institution": self.institution,
            "source_account": self.source_account,
            "ledger_account": self.ledger_account,
            "date": self.date,
            "description": self.description,
            "amount": self.amount,
            "currency": self.currency,
            "category": self.category,
            "category_source": self.category_source,
            "status": self.status,
            "imported_at": self.imported_at,
        }
        missing = [name for name, value in required.items() if value in (None, "")]
        if missing:
            raise ValueError(f"Missing required transaction fields: {', '.join(missing)}")

        try:
            datetime.strptime(self.date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Invalid date: {self.date}") from exc

        try:
            Decimal(str(self.amount))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid amount: {self.amount}") from exc

        if self.status not in VALID_STATUS:
            raise ValueError(f"Invalid status: {self.status}")

        if len(self.currency) != 3 or self.currency.upper() != self.currency:
            raise ValueError(f"Invalid currency: {self.currency}")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TransactionRecord":
        obj = cls(**data)
        obj.validate()
        return obj


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
