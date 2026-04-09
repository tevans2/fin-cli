from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AliasRule:
    name: str
    alias: str
    description_exact: str | None = None
    description_regex: str | None = None
    enabled: bool = True
    notes: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AliasRule":
        match = data.get("match", {})
        return cls(
            name=data["name"],
            alias=data["alias"],
            description_exact=match.get("description_exact"),
            description_regex=match.get("description_regex"),
            enabled=data.get("enabled", True),
            notes=data.get("notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        match: dict[str, str] = {}
        if self.description_exact:
            match["description_exact"] = self.description_exact
        if self.description_regex:
            match["description_regex"] = self.description_regex
        return {
            "name": self.name,
            "alias": self.alias,
            "enabled": self.enabled,
            "notes": self.notes,
            "match": match,
        }
