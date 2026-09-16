"""Auto-apply behavior of the categorize service against a throwaway data dir."""

from __future__ import annotations

import pytest

from finance.classify.allocation import Allocation
from finance.models.transaction import TransactionRecord
from finance.services.categorize import apply_splits, auto_apply, build_plan
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
