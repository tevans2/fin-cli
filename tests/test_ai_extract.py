"""AI PDF fallback — payload conversion and the fallback flow (no real API calls)."""

from __future__ import annotations

import pytest

from finance.statements.ai_extract import _call_openai, rows_from_ai_payload
from finance.statements.model import BalanceChainError, StatementFormatError, StatementRow
from finance.statements.parse import parse_statement
from finance.statements.profile import StatementProfile


def _pdf_profile(**overrides) -> StatementProfile:
    base = dict(name="acme", id_prefix="acme", format="pdf", date_formats=["%Y-%m-%d"])
    base.update(overrides)
    return StatementProfile(**base)


GOOD_PAYLOAD = {
    "transactions": [
        {"date": "2026-01-01", "description": "Opening buy", "amount": "-50.00", "balance": "-50.00"},
        {"date": "2026-01-02", "description": "Salary", "amount": "1000.00", "balance": "950.00"},
    ]
}


def test_rows_from_ai_payload_builds_rows():
    rows = rows_from_ai_payload(GOOD_PAYLOAD, _pdf_profile())
    assert [r.amount for r in rows] == ["-50.00", "1000.00"]
    assert rows[1].balance == "950.00"


def test_rows_from_ai_payload_rejects_empty():
    with pytest.raises(StatementFormatError):
        rows_from_ai_payload({"transactions": []}, _pdf_profile())


def test_rows_from_ai_payload_rejects_missing_amount():
    bad = {"transactions": [{"date": "2026-01-01", "description": "x"}]}
    with pytest.raises(StatementFormatError):
        rows_from_ai_payload(bad, _pdf_profile())


def test_ai_fallback_not_used_without_flag(monkeypatch, tmp_path):
    def boom(path, profile):
        raise StatementFormatError("no line_regex")

    monkeypatch.setattr("finance.statements.pdf_parser.parse_pdf", boom)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with pytest.raises(StatementFormatError):
        parse_statement(pdf, _pdf_profile(), ai_fallback=False)


def test_ai_fallback_extracts_and_validates(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "finance.statements.pdf_parser.parse_pdf",
        lambda path, profile: (_ for _ in ()).throw(StatementFormatError("regex matched nothing")),
    )
    ai_rows = rows_from_ai_payload(GOOD_PAYLOAD, _pdf_profile())
    monkeypatch.setattr(
        "finance.statements.ai_extract.extract_pdf_rows",
        lambda path, profile, reason="": ai_rows,
    )
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    rows, summary = parse_statement(pdf, _pdf_profile(), ai_fallback=True)
    assert len(rows) == 2
    assert summary.balance_chain_verified is True


def test_ai_fallback_output_is_still_balance_checked(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "finance.statements.pdf_parser.parse_pdf",
        lambda path, profile: (_ for _ in ()).throw(StatementFormatError("nope")),
    )
    bad_rows = [
        StatementRow(date="2026-01-01", description="a", amount="-50.00", balance="-50.00"),
        StatementRow(date="2026-01-02", description="b", amount="1000.00", balance="9999.00"),
    ]
    monkeypatch.setattr(
        "finance.statements.ai_extract.extract_pdf_rows",
        lambda path, profile, reason="": bad_rows,
    )
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with pytest.raises(BalanceChainError):
        parse_statement(pdf, _pdf_profile(), ai_fallback=True)


def test_call_openai_without_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(StatementFormatError) as exc:
        _call_openai("some text", currency="ZAR", model="gpt-4o-mini")
    assert "OPENAI_API_KEY" in str(exc.value)
