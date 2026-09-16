"""The classification engine: rules -> history -> nothing, with auto flags."""

from __future__ import annotations

from finance.classify.engine import classify
from finance.classify.history import build_history
from finance.models.rules import Rule, RuleMatch
from finance.models.transaction import TransactionRecord


def _rec(description, category="expenses:unknown", *, amount="-100.00"):
    return TransactionRecord(
        id=f"{description}-{id(object())}", institution="investec", source_account="checking",
        ledger_account="assets:bank:investec:checking", date="2026-01-01", description=description,
        amount=amount, currency="ZAR", category=category, category_source="manual",
        status="cleared", imported_at="2026-01-01T00:00:00Z",
    )


def _history(pairs):
    return build_history([_rec(d, c) for d, c in pairs])


def test_rule_match_auto_applies():
    rules = [Rule(name="pizza", category="expenses:lifestyle:eating-out",
                  match=RuleMatch(description_regex="pizza shed"))]
    result = classify(_rec("YOCO *PIZZA SHED CAPE TOWN ZA"), history=build_history([]), rules=rules)
    assert result.recommended == "expenses:lifestyle:eating-out"
    assert result.source == "rule:pizza"
    assert result.auto is True


def test_unknown_fallback_rules_are_ignored():
    # the default fallback rules assign expenses:unknown; the engine must not "auto" those
    rules = [Rule(name="fallback", category="expenses:unknown", match=RuleMatch(amount_lt="0"))]
    result = classify(_rec("MYSTERY SHOP"), history=build_history([]), rules=rules)
    assert result.recommended is None
    assert result.auto is False
    assert result.source == "none"


def test_confident_history_auto_applies():
    history = _history([("The Shack", "expenses:lifestyle:drinks")] * 5)
    result = classify(_rec("THE SHACK CAPE TOWN ZA"), history=history, rules=[])
    assert result.recommended == "expenses:lifestyle:drinks"
    assert result.auto is True
    assert result.source == "history"


def test_ambiguous_history_recommends_but_does_not_auto():
    history = _history([
        ("Punk Bar", "expenses:lifestyle:drinks"),
        ("Punk Bar", "expenses:lifestyle:drinks"),
        ("Punk Bar", "expenses:lifestyle:fast-food"),
    ])
    result = classify(_rec("YOCO *PUNK BAR STELLENBOSCH ZA"), history=history, rules=[])
    assert result.recommended == "expenses:lifestyle:drinks"
    assert result.auto is False                       # 67% < 95%
    assert [c.category for c in result.candidates] == [
        "expenses:lifestyle:drinks", "expenses:lifestyle:fast-food",
    ]
    assert result.candidates[0].share > result.candidates[1].share


def test_unknown_merchant_still_named_provisionally():
    result = classify(_rec("Purchase at NEVER SEEN BEFORE Cape Town ZA 123456"), history=build_history([]), rules=[])
    assert result.recommended is None
    assert result.auto is False
    assert result.merchant == "Never Seen Before"     # provisional identity from the key
