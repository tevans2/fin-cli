"""Parsing + balance-chain tests — no FIN_DATA_DIR needed (profiles passed directly)."""

from __future__ import annotations

import pytest

from finance.statements.balance import opening_balance, summarize, verify_balance_chain
from finance.statements.csv_parser import parse_csv
from finance.statements.model import BalanceChainError, StatementFormatError
from finance.statements.parse import parse_statement
from finance.statements.profile import BUILTIN_PROFILES, generic_profile, load_profile

INVESTEC_CSV = """Account Name:Mr TAT Evans  10013116355,,,,,
Transaction Date,Posting Date,Description,Debits,Credits,Balance
2026/01/03,2026/01/03,COFFEE   SHOP,50.00,,900.00
2026/01/02,2026/01/02,SALARY,,1000.00,950.00
2026/01/01,2026/01/01,OPENING PURCHASE,50.00,,-50.00
"""

TYME_SIGNED_CSV = """Date,Description,Amount,Balance
2026-02-01,Woolworths,-100.00,400.00
2026-02-02,Refund,50.00,450.00
"""

GENERIC_DEBIT_CREDIT_CSV = """Date,Description,Money Out,Money In,Balance
2026-04-01,Rent,5000.00,,1000.00
2026-04-02,Salary,,6000.00,7000.00
"""


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_investec_profile_parses_and_reverses_to_chronological(tmp_path):
    path = _write(tmp_path, "investec.csv", INVESTEC_CSV)
    rows, summary = parse_statement(path, BUILTIN_PROFILES["investec"]())
    assert [r.date for r in rows] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert rows[0].description == "OPENING PURCHASE"
    assert rows[2].description == "COFFEE SHOP"  # runs of spaces collapsed
    assert rows[1].amount == "1000.00"           # credit is positive
    assert rows[2].amount == "-50.00"            # debit is negative
    assert summary.balance_chain_verified is True
    assert summary.opening_balance == "0.00"
    assert summary.closing_balance == "900.00"


def test_balance_chain_catches_a_tampered_balance(tmp_path):
    tampered = INVESTEC_CSV.replace("900.00", "999.00")
    path = _write(tmp_path, "bad.csv", tampered)
    with pytest.raises(BalanceChainError) as exc:
        parse_statement(path, BUILTIN_PROFILES["investec"]())
    assert "inconsistent" in str(exc.value)


def test_tyme_signed_amount_profile(tmp_path):
    path = _write(tmp_path, "tyme.csv", TYME_SIGNED_CSV)
    rows, summary = parse_statement(path, BUILTIN_PROFILES["tyme"]())
    assert [r.amount for r in rows] == ["-100.00", "50.00"]
    assert summary.balance_chain_verified is True
    assert summary.opening_balance == "500.00"


def test_generic_profile_detects_debit_credit_aliases(tmp_path):
    path = _write(tmp_path, "fnb.csv", GENERIC_DEBIT_CREDIT_CSV)
    rows, summary = parse_statement(path, generic_profile("fnb"))
    assert [r.amount for r in rows] == ["-5000.00", "6000.00"]
    assert summary.balance_chain_verified is True


def test_amount_only_statement_skips_chain(tmp_path):
    path = _write(tmp_path, "noba.csv", "date,description,amount\n2026-03-01,Shop,-20.00\n")
    rows, summary = parse_statement(path, generic_profile("acme"))
    assert rows[0].balance is None
    assert summary.balance_chain_verified is False


def test_require_balance_chain_without_balance_errors(tmp_path):
    profile = generic_profile("strict")
    profile.require_balance_chain = True
    path = _write(tmp_path, "nb.csv", "date,description,amount\n2026-03-01,Shop,-20.00\n")
    with pytest.raises(BalanceChainError):
        parse_statement(path, profile)


def test_row_with_both_debit_and_credit_is_rejected(tmp_path):
    bad = "Date,Description,Debit,Credit\n2026-01-01,Weird,10.00,10.00\n"
    path = _write(tmp_path, "both.csv", bad)
    with pytest.raises(StatementFormatError):
        parse_csv(path, generic_profile("x"))


def test_missing_date_column_is_a_clear_error(tmp_path):
    path = _write(tmp_path, "nodate.csv", "Thing,Amount\nfoo,-1.00\n")
    with pytest.raises(StatementFormatError):
        parse_csv(path, generic_profile("x"))


def test_load_profile_prefers_config_file(tmp_path):
    statements = tmp_path / "statements"
    statements.mkdir()
    (statements / "fnb-checking.yaml").write_text(
        "name: fnb\nid_prefix: fnb\ncolumns:\n  date: [txn date]\n  description: [narrative]\n  amount: [value]\n"
    )
    profile = load_profile("fnb", "checking", config_dir=tmp_path)
    assert profile.id_prefix == "fnb"
    assert profile.columns["date"] == ["txn date"]


def test_load_profile_falls_back_to_builtin_then_generic(tmp_path):
    assert load_profile("investec", "checking", config_dir=tmp_path).id_prefix == "investec-csv"
    assert load_profile("unheardof", "checking", config_dir=tmp_path).id_prefix == "unheardof"


def test_verify_and_summarize_helpers_directly():
    from finance.statements.model import StatementRow

    rows = [
        StatementRow(date="2026-01-01", description="a", amount="-50.00", balance="-50.00"),
        StatementRow(date="2026-01-02", description="b", amount="1000.00", balance="950.00"),
    ]
    assert verify_balance_chain(rows) == []
    assert opening_balance(rows) == "0.00"
    s = summarize(rows, verified=True)
    assert s.total_debits == "-50.00"
    assert s.total_credits == "1000.00"
