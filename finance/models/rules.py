from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_MATCH_FIELDS = (
    "description_regex",
    "merchant",
    "account",
    "institution",
    "direction",
    "amount_lt",
    "amount_gt",
    "currency",
)


@dataclass
class RuleMatch:
    description_regex: str | None = None
    merchant: str | None = None          # matches the transaction's normalized merchant key
    account: str | None = None           # source_account, e.g. "checking"
    institution: str | None = None       # e.g. "investec"
    direction: str | None = None         # "in" (money in) | "out" (money out)
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
    auto_confirm: bool = False   # reserved: when True, matches skip the review queue (not wired yet)
    match: RuleMatch = field(default_factory=RuleMatch)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rule:
        raw_match = data.get("match", {}) or {}
        match = RuleMatch(**{k: v for k, v in raw_match.items() if k in _MATCH_FIELDS})
        return cls(
            name=data["name"],
            category=data["category"],
            priority=data.get("priority", 100),
            enabled=data.get("enabled", True),
            notes=data.get("notes"),
            auto_confirm=data.get("auto_confirm", False),
            match=match,
        )

    def to_dict(self) -> dict[str, Any]:
        match = {f: getattr(self.match, f) for f in _MATCH_FIELDS if getattr(self.match, f) not in (None, "")}
        data: dict[str, Any] = {"name": self.name, "category": self.category, "priority": self.priority}
        if not self.enabled:
            data["enabled"] = False
        if self.notes:
            data["notes"] = self.notes
        if self.auto_confirm:
            data["auto_confirm"] = True
        data["match"] = match
        return data
