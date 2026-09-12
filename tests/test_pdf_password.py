"""Password-protected PDF handling via <BANK>_DOC_CODE."""

from __future__ import annotations

import pytest

from finance.services.statement_import import doc_code_env_var, get_doc_code
from finance.statements.model import StatementFormatError
from finance.statements.parse import parse_statement
from finance.statements.pdf_parser import extract_lines
from finance.statements.profile import StatementProfile


def test_doc_code_env_var_naming():
    assert doc_code_env_var("investec") == "INVESTEC_DOC_CODE"
    assert doc_code_env_var("my-bank") == "MY_BANK_DOC_CODE"
    assert doc_code_env_var("fnb") == "FNB_DOC_CODE"


def test_get_doc_code_reads_env(monkeypatch):
    monkeypatch.setenv("INVESTEC_DOC_CODE", "pw123")
    assert get_doc_code("investec") == "pw123"


def test_get_doc_code_missing_is_none(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FIN_DATA_DIR", raising=False)
    monkeypatch.delenv("ACME_DOC_CODE", raising=False)
    assert get_doc_code("acme") is None


def test_extract_lines_password_error_hints_env_var(monkeypatch, tmp_path):
    import pdfplumber

    monkeypatch.setattr(pdfplumber, "open", lambda *a, **k: (_ for _ in ()).throw(ValueError("encrypted")))
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    with pytest.raises(StatementFormatError) as no_pw:
        extract_lines(pdf)
    assert "DOC_CODE" in str(no_pw.value)

    with pytest.raises(StatementFormatError) as wrong_pw:
        extract_lines(pdf, password="nope")
    assert "wrong password" in str(wrong_pw.value)


def test_pdf_password_threads_through_to_parser(monkeypatch, tmp_path):
    captured = {}

    def fake_parse_pdf(path, profile, password=None):
        captured["password"] = password
        raise StatementFormatError("stop")

    monkeypatch.setattr("finance.statements.pdf_parser.parse_pdf", fake_parse_pdf)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    profile = StatementProfile(name="investec", id_prefix="investec-csv", format="pdf")
    with pytest.raises(StatementFormatError):
        parse_statement(pdf, profile, pdf_password="s3cr3t")
    assert captured["password"] == "s3cr3t"
