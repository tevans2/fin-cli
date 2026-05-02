from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass
class InvestmentValuation:
    name: str
    account: str
    date: str
    value: str
    currency: str
    notes: str | None
    recorded_at: str

    def validate(self) -> None:
        try:
            datetime.strptime(self.date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Invalid date: {self.date}") from exc
        try:
            Decimal(self.value)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid value: {self.value}") from exc
        if len(self.currency) != 3 or self.currency.upper() != self.currency:
            raise ValueError(f"Invalid currency: {self.currency}")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InvestmentValuation":
        obj = cls(**data)
        obj.validate()
        return obj


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
