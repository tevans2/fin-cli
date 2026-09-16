"""Auto-apply behavior of the categorize service against a throwaway data dir."""

from __future__ import annotations

import pytest

from finance.classify.allocation import Allocation
from finance.models.transaction import TransactionRecord
from finance.services.categorize import (
    apply_category,
    apply_splits,
    auto_apply,
    build_plan,
    confirm,
    reject,
    restore_record,
    snapshot,
)
from finance.services.init_data import initialize_data_dir
from finance.services.transactions import load_bank_transactions
from finance.storage.jsonl_store import JsonlTransactionStore


def _rec(id_, description, category, *, amount="-50.00"):
    return TransactionRecord(
        id=id_, institution="investec", source_account="checking",
        ledger_account="assets:bank:investec:checking", date="2026-01-05", description=description,
        amount=amount, currency="ZAR", category=category, category_source="manual",
        status="cleared", imported_at="2026-01-05T00:00:00Z",
    )


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    initialize_data_dir(d)
    monkeypatch.setenv("FIN_DATA_DIR", str(d))
    store = JsonlTransactionStore(d / "transactions")
    records = [
        # consistent history: STARBUCKS -> coffee, 3 times
        _rec("h1", "STARBUCKS CAPE TOWN ZA", "expenses:coffee"),
        _rec("h2", "STARBUCKS CAPE TOWN ZA 111111", "expenses:coffee"),
        _rec("h3", "Purchase at STARBUCKS Cape Town ZA 222222", "expenses:coffee"),
        # an unknown STARBUCKS (should auto-apply) and an unseen merchant (should not)
        _rec("u1", "STARBUCKS CAPE TOWN ZA 333333", "expenses:unknown"),
        _rec("u2", "Purchase at MYSTERY DELI Cape Town ZA 444444", "expenses:unknown"),
    ]
    store.write_file(d / "transactions" / "investec" / "2026.jsonl", records)
    return d


def test_auto_apply_confident_only(data_dir):
    summary = auto_apply("investec")
    assert summary["auto_applied"] == 1     # only the known STARBUCKS
    assert summary["remaining"] == 1        # MYSTERY DELI still unknown

    by_id = {r.id: r for r in load_bank_transactions("investec")}
    assert by_id["u1"].category == "expenses:coffee"
    assert by_id["u1"].merchant == "Starbucks"
    assert by_id["u2"].category == "expenses:unknown"


def test_build_plan_recommends_for_remaining(data_dir):
    auto_apply("investec")
    plan = build_plan("investec")
    assert len(plan) == 1
    record, classification = plan[0]
    assert record.id == "u2"
    assert classification.recommended is None    # never seen -> no rec, needs manual
    assert classification.merchant == "Mystery Deli"


def test_all_scope_returns_every_transaction(data_dir):
    auto_apply("investec")   # clears the uncat inbox down to one
    all_ids = {rec.id for rec, _ in build_plan("investec", scope="all")}
    assert all_ids == {"h1", "h2", "h3", "u1", "u2"}   # categorized + reviewed included
    # newest-first ordering
    dates = [rec.date for rec, _ in build_plan("investec", scope="all")]
    assert dates == sorted(dates, reverse=True)


def test_auto_apply_marks_needs_review(data_dir):
    auto_apply("investec")
    by_id = {r.id: r for r in load_bank_transactions("investec")}
    assert by_id["u1"].category == "expenses:coffee"
    assert by_id["u1"].reviewed is False        # auto-guess -> review queue


def test_manual_apply_is_reviewed(data_dir):
    apply_category("investec", "u2", "expenses:other")
    assert {r.id: r for r in load_bank_transactions("investec")}["u2"].reviewed is True


def test_review_scope_and_confirm(data_dir):
    auto_apply("investec")
    in_review = {rec.id for rec, _ in build_plan("investec", scope="review")}
    assert "u1" in in_review
    assert confirm("investec", ["u1"]) == 1
    assert {r.id: r for r in load_bank_transactions("investec")}["u1"].reviewed is True
    assert "u1" not in {rec.id for rec, _ in build_plan("investec", scope="review")}


def test_reject_resets_to_uncategorized(data_dir):
    auto_apply("investec")
    assert reject("investec", "u1") is True
    r = {x.id: x for x in load_bank_transactions("investec")}["u1"]
    assert r.category == "expenses:unknown"
    assert r.reviewed is True                    # dealt with; back in the inbox


def test_classifier_cache_classifies(data_dir):
    from finance.classify.cache import Classifier

    classifier = Classifier()
    unknown_starbucks = [r for r in load_bank_transactions("investec") if r.id == "u1"][0]
    result = classifier.classify(unknown_starbucks)
    assert result.recommended == "expenses:coffee"


def test_snapshot_and_restore_round_trip(data_dir):
    # snapshot the uncategorized record, categorize it, then restore the snapshot
    before = snapshot("investec", "u2")
    assert before["category"] == "expenses:unknown"

    apply_category("investec", "u2", "expenses:other")
    after = snapshot("investec", "u2")
    assert after["category"] == "expenses:other"
    assert after["reviewed"] is True

    assert restore_record("investec", before) is True
    restored = {r.id: r for r in load_bank_transactions("investec")}["u2"]
    assert restored.category == "expenses:unknown"

    # redo direction: restore the "after" snapshot
    assert restore_record("investec", after) is True
    assert {r.id: r for r in load_bank_transactions("investec")}["u2"].category == "expenses:other"


def test_restore_unknown_id_is_noop(data_dir):
    ghost = snapshot("investec", "u2")
    ghost["id"] = "does-not-exist"
    assert restore_record("investec", ghost) is False


def test_apply_splits_partitions_amount(data_dir):
    record = [r for r in load_bank_transactions("investec") if r.id == "u2"][0]
    ok = apply_splits(
        "investec", record,
        [Allocation("expenses:lifestyle:drinks", "20.00"), Allocation("expenses:lifestyle:eating-out", "30.00")],
    )
    assert ok
    stored = {r.id: r for r in load_bank_transactions("investec")}["u2"]
    assert stored.category == "split"
    assert sum(float(s.amount) for s in stored.splits) == 50.00
