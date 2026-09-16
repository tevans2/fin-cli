"""Category rename/merge migration — token safety and end-to-end."""

from __future__ import annotations

import pytest

from finance.models.transaction import TransactionRecord, TransactionSplit
from finance.services.categories import rename_category, replace_account_token
from finance.services.init_data import initialize_data_dir
from finance.services.transactions import load_bank_transactions
from finance.storage.jsonl_store import JsonlTransactionStore


def test_replace_account_token_is_prefix_safe():
    text = "account expenses:holiday\naccount expenses:holiday:accommodation\n"
    out = replace_account_token(text, "expenses:holiday", "expenses:holiday:other")
    assert "account expenses:holiday:other\n" in out
    assert "expenses:holiday:accommodation" in out            # NOT corrupted
    assert "expenses:holiday:other:accommodation" not in out


def test_replace_account_token_exact_only():
    text = "- expenses:lifestyle:drinks\n- expenses:lifestyle:drinks-special\n"
    out = replace_account_token(text, "expenses:lifestyle:drinks", "expenses:lifestyle:bars")
    assert "- expenses:lifestyle:bars\n" in out
    assert "expenses:lifestyle:drinks-special" in out          # hyphen-suffixed left alone


def _rec(id_, category, amount="-50.00", splits=None):
    return TransactionRecord(
        id=id_, institution="investec", source_account="checking",
        ledger_account="assets:bank:investec:checking", date="2026-01-05", description="x",
        amount=amount, currency="ZAR", category=category, category_source="manual",
        status="cleared", imported_at="2026-01-05T00:00:00Z", splits=splits or [],
    )


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    initialize_data_dir(d)
    monkeypatch.setenv("FIN_DATA_DIR", str(d))
    store = JsonlTransactionStore(d / "transactions")
    store.write_file(d / "transactions" / "investec" / "2026.jsonl", [
        _rec("a", "expenses:lifestyle:drinks"),
        _rec("b", "expenses:lifestyle:drinks"),
        _rec("c", "expenses:lifestyle:jol"),
        _rec("d", "split", splits=[
            TransactionSplit("expenses:lifestyle:drinks", "20.00"),
            TransactionSplit("expenses:groceries", "30.00"),
        ]),
    ])
    return d


def test_rename_updates_transactions_and_splits(data_dir):
    result = rename_category("expenses:lifestyle:drinks", "expenses:lifestyle:bars")
    assert result["transactions"] == 3   # a, b, and the split record d

    by_id = {r.id: r for r in load_bank_transactions("investec")}
    assert by_id["a"].category == "expenses:lifestyle:bars"
    assert by_id["d"].splits[0].account == "expenses:lifestyle:bars"
    assert by_id["d"].splits[1].account == "expenses:groceries"   # untouched


def test_rename_is_a_merge_when_target_exists(data_dir):
    rename_category("expenses:lifestyle:drinks", "expenses:lifestyle:bars")
    rename_category("expenses:lifestyle:jol", "expenses:lifestyle:bars")
    cats = {r.category for r in load_bank_transactions("investec")}
    assert "expenses:lifestyle:bars" in cats
    assert "expenses:lifestyle:drinks" not in cats
    assert "expenses:lifestyle:jol" not in cats


def test_rename_rejects_noop():
    with pytest.raises(ValueError):
        rename_category("expenses:x", "expenses:x")
