"""PDF line-parsing tests (pure: no real PDF needed)."""

from __future__ import annotations

import pytest

from finance.statements.balance import opening_balance, verify_balance_chain
from finance.statements.model import StatementFormatError
from finance.statements.pdf_parser import rows_from_lines
from finance.statements.profile import StatementProfile

LINE_REGEX = (
    r"(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<description>.+?)\s+"
    r"(?P<amount>[\d,]+\.\d{2})(?P<direction>-?)\s+(?P<balance>[\d,]+\.\d{2})"
)

SAMPLE_LINES = [
    "ACME BANK — Statement",          # noise, skipped
    "Date Description Amount Balance",  # header-ish noise, skipped
    "01/04/2026 Woolworths Food 350.00- 12150.00",
    "02/04/2026 Salary 45000.00 57150.00",
    "Page 1 of 2",                    # noise, skipped
]


def _profile(**overrides) -> StatementProfile:
    base = dict(
        name="acme",
        id_prefix="acme",
        format="pdf",
        date_formats=["%d/%m/%Y"],
        order="chronological",
        pdf={"line_regex": LINE_REGEX},
    )
    base.update(overrides)
    return StatementProfile(**base)


def test_rows_from_lines_extracts_transactions_and_ignores_noise():
    rows = rows_from_lines(SAMPLE_LINES, _profile())
    assert len(rows) == 2
    assert rows[0].date == "2026-04-01"
    assert rows[0].description == "Woolworths Food"
    assert rows[0].amount == "-350.00"   # trailing '-' => debit
    assert rows[1].amount == "45000.00"  # no marker => credit
    assert rows[1].balance == "57150.00"


def test_pdf_rows_pass_the_balance_chain():
    rows = rows_from_lines(SAMPLE_LINES, _profile())
    assert verify_balance_chain(rows) == []
    assert opening_balance(rows) == "12500.00"


def test_pdf_broken_balance_is_caught_by_chain():
    lines = list(SAMPLE_LINES)
    lines[3] = "02/04/2026 Salary 45000.00 99999.00"  # wrong running balance
    rows = rows_from_lines(lines, _profile())
    assert verify_balance_chain(rows) != []


def test_missing_line_regex_is_a_clear_error():
    with pytest.raises(StatementFormatError):
        rows_from_lines(SAMPLE_LINES, _profile(pdf={}))


def test_no_matching_lines_raises():
    with pytest.raises(StatementFormatError):
        rows_from_lines(["nothing here", "still nothing"], _profile())
