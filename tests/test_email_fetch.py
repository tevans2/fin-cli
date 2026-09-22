"""IMAP statement fetching: attachment extraction, import, and message-id dedup."""

from __future__ import annotations

import imaplib
from email.message import EmailMessage
from types import SimpleNamespace

import pytest
import yaml

from finance.services import email_fetch
from finance.services.init_data import initialize_data_dir


def _raw_message(msgid: str) -> bytes:
    msg = EmailMessage()
    msg["Message-ID"] = msgid
    msg["From"] = "statements@tyme.example"
    msg["Subject"] = "Your TymeBank statement"
    msg.set_content("See attached.")
    msg.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="tyme-aug.pdf")
    return msg.as_bytes()


class FakeIMAP:
    """Minimal IMAP server with one message carrying a PDF attachment."""

    def __init__(self, raw: bytes, msgid: str):
        self.raw = raw
        self.msgid = msgid

    def login(self, u, p):
        return ("OK", [b""])

    def select(self, mailbox, readonly=False):
        return ("OK", [b"1"])

    def uid(self, cmd, *args):
        cmd = cmd.upper()
        if cmd == "SEARCH":
            return ("OK", [b"1"])
        if cmd == "FETCH":
            spec = args[1]
            if "MESSAGE-ID" in spec:
                return ("OK", [(b"1 (...)", f"Message-ID: {self.msgid}\r\n\r\n".encode())])
            return ("OK", [(b"1 (...)", self.raw)])
        return ("OK", [b""])

    def logout(self):
        return ("OK", [b""])


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    initialize_data_dir(d)
    monkeypatch.setenv("FIN_DATA_DIR", str(d))
    monkeypatch.setenv("GMAIL_USER", "me@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-pass-1234567")
    banks_dir = d / "config" / "banks"
    banks_dir.mkdir(parents=True, exist_ok=True)
    (banks_dir / "tyme.yaml").write_text(yaml.safe_dump({
        "name": "TymeBank", "currency": "ZAR",
        "ingest": {
            "source": "pdf",
            "email": {"host": "imap.gmail.com", "mailbox": "tyme-statement",
                      "user_env": "GMAIL_USER", "password_env": "GMAIL_APP_PASSWORD"},
        },
        "accounts": {"checking": {"ledger_account": "assets:bank:tyme:checking"}},
    }))
    return d


def _stub_import(calls):
    def _imp(path, **kw):
        calls.append(str(path))
        return {"inserted": 2, "skipped_already_present": 0,
                "summary": SimpleNamespace(balance_chain_verified=True)}
    return _imp


def test_email_banks_detects_config(data_dir):
    assert "tyme" in email_fetch.email_banks()


def test_fetch_imports_attachment_then_dedups(data_dir, monkeypatch):
    raw = _raw_message("<msg-1@tyme>")
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda *a, **k: FakeIMAP(raw, "<msg-1@tyme>"))
    calls: list[str] = []
    monkeypatch.setattr("finance.services.email_fetch.import_statement", _stub_import(calls))

    first = email_fetch.fetch_and_import("tyme")
    assert first["scanned"] == 1
    assert first["imported"] == 2
    assert first["files"][0]["ok"] is True
    assert len(calls) == 1

    # second run: the message-id is already recorded → nothing re-imported
    second = email_fetch.fetch_and_import("tyme")
    assert second["scanned"] == 0
    assert second["imported"] == 0
    assert len(calls) == 1


def test_fetch_no_email_config_raises(data_dir, monkeypatch):
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda *a, **k: FakeIMAP(b"", ""))
    with pytest.raises(ValueError):
        email_fetch.fetch_and_import("investec")  # legacy bank, no ingest.email


def test_dry_run_does_not_record_state(data_dir, monkeypatch):
    raw = _raw_message("<msg-2@tyme>")
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda *a, **k: FakeIMAP(raw, "<msg-2@tyme>"))
    calls: list[str] = []
    monkeypatch.setattr("finance.services.email_fetch.import_statement", _stub_import(calls))

    email_fetch.fetch_and_import("tyme", dry_run=True)
    # dry-run doesn't persist the message-id, so a real run still processes it
    again = email_fetch.fetch_and_import("tyme")
    assert again["scanned"] == 1
