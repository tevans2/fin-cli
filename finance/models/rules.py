from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuleMatch:
    description_regex: str | None = None
    amount_lt: str | None = None
    amount_gt: str | None = None
    currency: str | None = None


@dataclass
class Rule:
    name: str
    category: str
    priority: int = 100
    enabled: bool = True
    notes: str | None = None
    match: RuleMatch = field(default_factory=RuleMatch)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rule":
        match = RuleMatch(**data.get("match", {}))
        return cls(
            name=data["name"],
            category=data["category"],
            priority=data.get("priority", 100),
            enabled=data.get("enabled", True),
            notes=data.get("notes"),
            match=match,
        )
