"""End-to-end import against a throwaway FIN_DATA_DIR."""

from __future__ import annotations

import json

import pytest

from finance.services.init_data import initialize_data_dir
from finance.services.statement_import import import_statement

INVESTEC_CSV = """Account Name:Mr TAT Evans  10013116355,,,,,
Transaction Date,Posting Date,Description,Debits,Credits,Balance
2026/01/03,2026/01/03,COFFEE SHOP,50.00,,900.00
2026/01/02,2026/01/02,SALARY,,1000.00,950.00
2026/01/01,2026/01/01,OPENING PURCHASE,50.00,,-50.00
"""


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    initialize_data_dir(d)
    monkeypatch.setenv("FIN_DATA_DIR", str(d))
    return d


def _stmt(data_dir):
    path = data_dir.parent / "stmt.csv"
    path.write_text(INVESTEC_CSV)
    return path


def test_import_investec_end_to_end(data_dir):
    result = import_statement(_stmt(data_dir), bank="investec", account="savings")
    assert result["inserted"] == 3
    assert result["summary"].balance_chain_verified is True

    year_file = data_dir / "transactions" / "investec" / "2026.jsonl"
    records = [json.loads(line) for line in year_file.read_text().splitlines()]
    assert len(records) == 3
    assert all(r["currency"] == "ZAR" for r in records)
    assert all(r["ledger_account"] == "assets:bank:investec:savings" for r in records)

    journal = (data_dir / "journal" / "generated" / "investec.journal").read_text()
    assert "1000.00 ZAR" in journal  # salary credit rendered as Decimal


def test_reimport_is_idempotent(data_dir):
    import_statement(_stmt(data_dir), bank="investec", account="savings")
    again = import_statement(_stmt(data_dir), bank="investec", account="savings")
    assert again["inserted"] == 0
    assert again["skipped_already_present"] == 3


# same transactions (dates, amounts, running balances) but re-extracted with
# different description text — as the AI fallback can produce on a re-import.
INVESTEC_CSV_DRIFT = """Account Name:Mr TAT Evans  10013116355,,,,,
Transaction Date,Posting Date,Description,Debits,Credits,Balance
2026/01/03,2026/01/03,COFFEE SHOP DOWNTOWN 12345,50.00,,900.00
2026/01/02,2026/01/02,SALARY PAYMENT ACME,,1000.00,950.00
2026/01/01,2026/01/01,OPENING PURCHASE REF99,50.00,,-50.00
"""


def test_reimport_dedups_despite_description_drift(data_dir):
    import_statement(_stmt(data_dir), bank="investec", account="savings")
    drift = data_dir.parent / "stmt2.csv"
    drift.write_text(INVESTEC_CSV_DRIFT)
    again = import_statement(drift, bank="investec", account="savings")
    # descriptions differ but the running balances match → recognized as the same rows
    assert again["inserted"] == 0
    assert again["skipped_already_present"] == 3
    year_file = data_dir / "transactions" / "investec" / "2026.jsonl"
    assert len(year_file.read_text().splitlines()) == 3


def test_dry_run_writes_nothing(data_dir):
    result = import_statement(_stmt(data_dir), bank="investec", account="savings", dry_run=True)
    assert result["inserted"] == 3
    assert not (data_dir / "transactions" / "investec" / "2026.jsonl").exists()


def test_broken_chain_refuses_before_writing(data_dir):
    from finance.statements.model import BalanceChainError

    path = data_dir.parent / "bad.csv"
    path.write_text(INVESTEC_CSV.replace("900.00", "999.00"))
    with pytest.raises(BalanceChainError):
        import_statement(path, bank="investec", account="savings")
    assert not (data_dir / "transactions" / "investec" / "2026.jsonl").exists()
