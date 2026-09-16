"""Category taxonomy: loading, validation, seeding, and drift detection."""

from __future__ import annotations

from finance.classify.taxonomy import (
    Taxonomy,
    categories_in_use,
    load_taxonomy,
    unlisted_categories,
    write_taxonomy,
)
from finance.models.transaction import TransactionRecord, TransactionSplit


def _rec(category="expenses:food", splits=None):
    return TransactionRecord(
        id="t", institution="investec", source_account="checking",
        ledger_account="assets:bank:investec:checking", date="2026-01-01",
        description="x", amount="-10.00", currency="ZAR", category=category,
        category_source="manual", status="cleared", imported_at="2026-01-01T00:00:00Z",
        splits=splits or [],
    )


def test_unenforced_when_empty_allows_all():
    tax = Taxonomy()
    assert not tax.enforced
    assert tax.is_valid("anything:goes")


def test_enforced_validates_membership():
    tax = Taxonomy({"expenses:food", "income:salary"})
    assert tax.enforced
    assert tax.is_valid("expenses:food")
    assert tax.is_valid("split")            # structural marker always allowed
    assert not tax.is_valid("expenses:typo")


def test_roots():
    tax = Taxonomy({"expenses:food:groceries", "income:salary", "assets:bank:x"})
    assert tax.roots() == ["assets", "expenses", "income"]


def test_categories_in_use_includes_split_accounts():
    records = [
        _rec(category="expenses:food"),
        _rec(category="split", splits=[
            TransactionSplit("expenses:a", "5.00"), TransactionSplit("expenses:b", "5.00"),
        ]),
    ]
    used = categories_in_use(records)
    assert used == {"expenses:food", "expenses:a", "expenses:b"}
    assert "split" not in used


def test_seed_write_and_reload(tmp_path):
    path = tmp_path / "categories.yaml"
    write_taxonomy(path, {"expenses:food", "income:salary"})
    reloaded = load_taxonomy(path)
    assert reloaded.categories == {"expenses:food", "income:salary"}


def test_unlisted_categories_flags_drift():
    tax = Taxonomy({"expenses:food"})
    records = [_rec(category="expenses:food"), _rec(category="expenses:diningg")]
    assert unlisted_categories(records, tax) == {"expenses:diningg"}


def test_missing_file_is_unenforced(tmp_path):
    assert not load_taxonomy(tmp_path / "nope.yaml").enforced
