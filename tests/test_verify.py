"""Tests for ledger-vs-bank reconciliation."""

from __future__ import annotations

import shutil
from decimal import Decimal

import pytest

from finance.services.init_data import initialize_data_dir
from finance.services.statement_import import import_statement
from finance.services.verify import (
    latest_statement_balances,
    parse_hledger_amount,
    verify_accounts,
)

INVESTEC_CSV = """Account Name:Mr TAT Evans  10013116355,,,,,
Transaction Date,Posting Date,Description,Debits,Credits,Balance
2026/01/03,2026/01/03,COFFEE SHOP,50.00,,900.00
2026/01/02,2026/01/02,SALARY,,1000.00,950.00
2026/01/01,2026/01/01,OPENING PURCHASE,50.00,,-50.00
"""


def _rec(**overrides):
    from finance.models.transaction import TransactionRecord

    base = dict(
        id="x",
        institution="investec",
        source_account="checking",
        ledger_account="assets:bank:investec:checking",
        date="2026-01-01",
        description="d",
        amount="-10.00",
        currency="ZAR",
        category="expenses:unknown",
        category_source="default:unknown",
        status="cleared",
        imported_at="2026-01-01T00:00:00Z",
    )
    base.update(overrides)
    return TransactionRecord(**base)


def test_parse_hledger_amount_variants():
    assert parse_hledger_amount("750.00 ZAR") == Decimal("750.00")
    assert parse_hledger_amount("-1,234.56 ZAR") == Decimal("-1234.56")
    assert parse_hledger_amount("ZAR 12.00") == Decimal("12.00")
    assert parse_hledger_amount("") is None


def test_latest_statement_balance_picks_newest_and_ignores_balanceless():
    records = [
        _rec(id="a", date="2026-01-01", provider_metadata={"balance": "100.00"}),
        _rec(id="b", date="2026-01-02", provider_metadata={"balance": "200.00"}),
        _rec(id="c", date="2026-01-03", provider_metadata={"balance": None}),
    ]
    best = latest_statement_balances(records)
    assert best[("investec", "checking")]["balance"] == "200.00"


def test_latest_statement_balance_tiebreaks_on_statement_line():
    records = [
        _rec(id="a", date="2026-01-02", provider_metadata={"balance": "100.00", "statement_line": 5}),
        _rec(id="b", date="2026-01-02", provider_metadata={"balance": "300.00", "statement_line": 9}),
    ]
    best = latest_statement_balances(records)
    assert best[("investec", "checking")]["balance"] == "300.00"


@pytest.mark.skipif(shutil.which("hledger") is None, reason="hledger not installed")
def test_verify_reconciles_after_import(tmp_path, monkeypatch):
    d = tmp_path / "data"
    initialize_data_dir(d)
    monkeypatch.setenv("FIN_DATA_DIR", str(d))
    stmt = tmp_path / "stmt.csv"
    stmt.write_text(INVESTEC_CSV)

    import_statement(stmt, bank="investec", account="savings")
    results = verify_accounts()

    savings = [r for r in results if r["source_account"] == "savings"]
    assert len(savings) == 1
    row = savings[0]
    assert row["statement_balance"] == Decimal("900.00")
    assert row["ledger_balance"] == Decimal("900.00")
    assert row["ok"] is True
