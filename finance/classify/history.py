"""Learn merchants and categories from already-categorized transactions.

Builds, once, a map of ``merchant_key -> category distribution`` from history, so
a new transaction keyed to a known merchant gets that merchant's usual category
plus a confidence (how consistent past choices were). Exact keys are tried first,
then a conservative fuzzy match for near-misses. Cross-bank: a merchant seen on
Investec informs the same merchant on Tyme.

This replaces the old exact-description suggester, which was O(n^2) (it reloaded
and rescanned every transaction for each row) and missed anything whose ref or
date differed.
"""

from __future__ import annotations

import difflib
from collections import Counter
from dataclasses import dataclass, field

from finance.classify.normalize import merchant_key
from finance.models.transaction import TransactionRecord

UNKNOWN_CATEGORIES = {"expenses:unknown", "income:unknown"}

# Confident enough to auto-apply (the agreed policy).
AUTO_APPLY_CONFIDENCE = 0.95
AUTO_APPLY_MIN_SAMPLES = 3

_FUZZY_CUTOFF = 0.85


@dataclass
class MerchantStats:
    key: str
    category_counts: Counter = field(default_factory=Counter)
    name_counts: Counter = field(default_factory=Counter)

    @property
    def samples(self) -> int:
        return sum(self.category_counts.values())

    @property
    def top_category(self) -> str:
        return self.category_counts.most_common(1)[0][0]

    @property
    def confidence(self) -> float:
        total = self.samples
        return self.category_counts.most_common(1)[0][1] / total if total else 0.0

    @property
    def display_name(self) -> str:
        if self.name_counts:
            return self.name_counts.most_common(1)[0][0]
        return self.key.title()

    @property
    def conflicted(self) -> bool:
        """More than one category has ever been used for this merchant."""
        return len(self.category_counts) > 1

    def breakdown(self) -> list[tuple[str, int, float]]:
        """(category, count, share) for every category seen, most common first."""
        total = self.samples
        return [
            (category, count, round(count / total, 4) if total else 0.0)
            for category, count in self.category_counts.most_common()
        ]


@dataclass
class Suggestion:
    merchant: str
    category: str
    confidence: float
    samples: int
    source: str  # "history" | "history:fuzzy"

    @property
    def is_confident(self) -> bool:
        return self.confidence >= AUTO_APPLY_CONFIDENCE and self.samples >= AUTO_APPLY_MIN_SAMPLES


@dataclass
class HistoryModel:
    by_key: dict[str, MerchantStats] = field(default_factory=dict)

    def merchants(self) -> list[MerchantStats]:
        return sorted(self.by_key.values(), key=lambda s: (-s.samples, s.key))

    def suggest(self, key: str, *, allow_fuzzy: bool = True) -> Suggestion | None:
        if not key:
            return None
        stats = self.by_key.get(key)
        source = "history"
        if stats is None and allow_fuzzy:
            match = difflib.get_close_matches(key, list(self.by_key), n=1, cutoff=_FUZZY_CUTOFF)
            if match:
                stats = self.by_key[match[0]]
                source = "history:fuzzy"
        if stats is None or stats.samples == 0:
            return None
        confidence = stats.confidence
        if source == "history:fuzzy":
            confidence = min(confidence, difflib.SequenceMatcher(None, key, stats.key).ratio())
        return Suggestion(
            merchant=stats.display_name,
            category=stats.top_category,
            confidence=round(confidence, 4),
            samples=stats.samples,
            source=source,
        )

    def suggest_for(self, record: TransactionRecord, *, allow_fuzzy: bool = True) -> Suggestion | None:
        return self.suggest(merchant_key(record.description), allow_fuzzy=allow_fuzzy)


def matching_records(records: list[TransactionRecord], key: str) -> list[TransactionRecord]:
    """Every transaction whose description normalizes to ``key`` (for verification)."""
    return [r for r in records if merchant_key(r.description) == key]


def build_history(records: list[TransactionRecord]) -> HistoryModel:
    by_key: dict[str, MerchantStats] = {}
    for record in records:
        if not record.category or record.category == "split" or record.category in UNKNOWN_CATEGORIES:
            continue
        key = merchant_key(record.description)
        if not key:
            continue
        stats = by_key.setdefault(key, MerchantStats(key))
        stats.category_counts[record.category] += 1
        name = record.alias or record.merchant  # a clean display name, not the raw description
        if name:
            stats.name_counts[name] += 1
    return HistoryModel(by_key)
