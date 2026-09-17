"""Turn a transaction into a recommendation: merchant + best category + alternatives.

Layers, highest priority first:
  1. explicit rules   — deterministic; auto-applies (source ``rule:<name>``)
  2. learned history  — the merchant's usual category + confidence; auto-applies
                        only when genuinely consistent (>=95%, >=3 samples)
  3. nothing known    — no recommendation, but still names a provisional merchant

Every result carries ranked ``candidates`` (the merchant's category distribution)
so the review UI can pre-fill the top pick and offer the rest as one-key choices,
and ``auto`` says whether it's safe to apply without asking.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from finance.classify.history import UNKNOWN_CATEGORIES, HistoryModel
from finance.classify.normalize import merchant_key
from finance.models.rules import Rule
from finance.models.transaction import TransactionRecord
from finance.storage.rules_store import match_rule


@dataclass
class Candidate:
    category: str
    share: float          # 0..1, how often this merchant used the category
    count: int = 0


@dataclass
class Classification:
    merchant: str | None
    recommended: str | None                 # best-guess category (None if unknown)
    confidence: float
    source: str                             # "rule:<name>" | "history" | "history:fuzzy" | "none"
    candidates: list[Candidate] = field(default_factory=list)
    auto: bool = False                      # safe to apply without asking
    merchant_key: str | None = None         # normalized identity, for merchant lookups


def _merchant_name(key: str, history: HistoryModel) -> str | None:
    stats = history.by_key.get(key)
    if stats is not None:
        return stats.display_name
    return key.title() or None


def classify(
    record: TransactionRecord,
    *,
    history: HistoryModel,
    rules: list[Rule],
) -> Classification:
    key = merchant_key(record.description)
    merchant = _merchant_name(key, history)

    # 1. explicit rules (skip the default unknown-fallback rules — those aren't real)
    for rule in rules:
        if rule.category in UNKNOWN_CATEGORIES:
            continue
        if match_rule(rule, record):
            return Classification(
                merchant=merchant,
                recommended=rule.category,
                confidence=1.0,
                source=f"rule:{rule.name}",
                candidates=[Candidate(rule.category, 1.0)],
                auto=True,
                merchant_key=key,
            )

    # 2. learned history
    stats = history.by_key.get(key)
    candidates = (
        [Candidate(cat, share, count) for cat, count, share in stats.breakdown()] if stats else []
    )
    suggestion = history.suggest(key)
    if suggestion:
        return Classification(
            merchant=merchant,
            recommended=suggestion.category,
            confidence=suggestion.confidence,
            source=suggestion.source,
            candidates=candidates,
            auto=suggestion.is_confident,
            merchant_key=key,
        )

    # 3. nothing known
    return Classification(
        merchant=merchant,
        recommended=None,
        confidence=0.0,
        source="none",
        candidates=candidates,
        auto=False,
        merchant_key=key,
    )
