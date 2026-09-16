"""History learning: merchant/category suggestions with confidence."""

from __future__ import annotations

from finance.classify.history import build_history
from finance.models.transaction import TransactionRecord


def _rec(description, category, *, bank="investec", alias=None, source="manual"):
    return TransactionRecord(
        id=f"{description}-{category}-{id(object())}",
        institution=bank, source_account="checking",
        ledger_account=f"assets:bank:{bank}:checking", date="2026-01-01",
        description=description, amount="-100.00", currency="ZAR",
        category=category, category_source=source, status="cleared",
        imported_at="2026-01-01T00:00:00Z", alias=alias,
    )


def test_exact_suggestion_and_confidence():
    records = [
        _rec("Purchase at Yoco *Pizza Shed Cape Town ZA 622716900111", "expenses:lifestyle:eating-out"),
        _rec("YOCO *PIZZA SHED CAPE TOWN ZA", "expenses:lifestyle:eating-out"),
        _rec("Purchase at Yoco *Pizza Shed Cape Town ZA 622716900222", "expenses:lifestyle:eating-out"),
    ]
    model = build_history(records)
    s = model.suggest("pizza shed")
    assert s.category == "expenses:lifestyle:eating-out"
    assert s.samples == 3
    assert s.confidence == 1.0
    assert s.is_confident   # >=95%, >=3 samples
    assert s.source == "history"


def test_mixed_history_lowers_confidence_below_auto():
    records = [
        _rec("Woolworths", "expenses:groceries"),
        _rec("Woolworths", "expenses:groceries"),
        _rec("Woolworths", "expenses:shopping:clothing"),
    ]
    s = build_history(records).suggest("woolworths")
    assert s.category == "expenses:groceries"
    assert round(s.confidence, 2) == 0.67
    assert not s.is_confident


def test_cross_bank_learning():
    records = [
        _rec("EFT for SPLITWISE", "expenses:other", bank="investec"),
        _rec("EFT for SPLITWISE", "expenses:other", bank="tyme"),
        _rec("EFT for SPLITWISE", "expenses:other", bank="tyme"),
    ]
    s = build_history(records).suggest("splitwise")
    assert s.samples == 3 and s.is_confident


def test_unknown_and_split_excluded_from_training():
    records = [
        _rec("Foo", "expenses:unknown"),
        _rec("Foo", "split"),
        _rec("Foo", "expenses:data"),
    ]
    s = build_history(records).suggest("foo")
    assert s.category == "expenses:data" and s.samples == 1


def test_fuzzy_match_for_near_key():
    records = [_rec("Pizza Shed", "expenses:lifestyle:eating-out")] * 1
    model = build_history(records)
    s = model.suggest("pizza shedd", allow_fuzzy=True)   # typo
    assert s is not None and s.source == "history:fuzzy"
    assert model.suggest("pizza shedd", allow_fuzzy=False) is None


def test_display_name_prefers_alias_then_titlecase():
    with_alias = build_history([_rec("YOCO *PIZZA SHED CAPE TOWN ZA", "expenses:lifestyle:eating-out", alias="Pizza Shed")])
    assert with_alias.suggest("pizza shed").merchant == "Pizza Shed"
    without = build_history([_rec("YOCO *PIZZA SHED CAPE TOWN ZA", "expenses:lifestyle:eating-out")])
    assert without.suggest("pizza shed").merchant == "Pizza Shed"  # title-cased key


def test_no_suggestion_for_unseen():
    assert build_history([]).suggest("whatever") is None
