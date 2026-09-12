"""Correctness tests for journal rendering and the JSONL store."""

from __future__ import annotations

from decimal import Decimal

from finance.models.transaction import TransactionRecord, TransactionSplit
from finance.services.journal import _format_amount, _render_transaction
from finance.storage.jsonl_store import JsonlTransactionStore


def _record(**overrides) -> TransactionRecord:
    base = dict(
        id="t1",
        institution="investec",
        source_account="checking",
        ledger_account="assets:bank:investec:checking",
        date="2026-01-15",
        description="COFFEE SHOP",
        amount="-1234.56",
        currency="ZAR",
        category="expenses:food",
        category_source="manual",
        status="cleared",
        imported_at="2026-01-15T10:00:00Z",
    )
    base.update(overrides)
    return TransactionRecord(**base)


def test_format_amount_uses_decimal_not_float():
    assert _format_amount("-1234.56", "ZAR") == "-1234.56 ZAR"
    assert _format_amount(Decimal("-50"), "ZAR") == "-50.00 ZAR"
    assert _format_amount("0", "ZAR") == "0.00 ZAR"


def test_render_two_posting_transaction_balances():
    out = _render_transaction(_record())
    assert "assets:bank:investec:checking    -1234.56 ZAR" in out
    assert "expenses:food    1234.56 ZAR" in out
    # the two amounts must be exact negatives of each other
    amounts = [Decimal(line.split()[-2]) for line in out.splitlines() if " ZAR" in line]
    assert sum(amounts) == Decimal("0.00")


def test_render_split_transaction():
    rec = _record(
        amount="-300.00",
        category="split",
        splits=[
            TransactionSplit(account="expenses:food", amount="200.00"),
            TransactionSplit(account="expenses:fun", amount="100.00", notes="treat"),
        ],
    )
    out = _render_transaction(rec)
    assert "expenses:food    200.00 ZAR" in out
    assert "expenses:fun    100.00 ZAR  ; treat" in out


def test_jsonl_store_round_trip(tmp_path):
    store = JsonlTransactionStore(tmp_path)
    path = tmp_path / "investec" / "2026.jsonl"
    store.write_file(path, [_record(id="b"), _record(id="a", date="2026-01-01")])
    back = store.read_file(path)
    # sorted by (date, id)
    assert [r.id for r in back] == ["a", "b"]
    assert back[1].amount == "-1234.56"


def test_jsonl_write_is_atomic_leaves_no_temp_files(tmp_path):
    store = JsonlTransactionStore(tmp_path)
    path = tmp_path / "investec" / "2026.jsonl"
    store.write_file(path, [_record()])
    leftovers = [p.name for p in (tmp_path / "investec").iterdir() if p.name != "2026.jsonl"]
    assert leftovers == []


def test_jsonl_overwrite_replaces_content(tmp_path):
    store = JsonlTransactionStore(tmp_path)
    path = tmp_path / "investec" / "2026.jsonl"
    store.write_file(path, [_record(id="x")])
    store.write_file(path, [_record(id="y")])
    assert [r.id for r in store.read_file(path)] == ["y"]
