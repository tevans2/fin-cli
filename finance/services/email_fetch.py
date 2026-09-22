"""Pull statement PDFs straight from an IMAP mailbox and import them.

A bank with an ``ingest.email`` block can have its statements polled from a Gmail
label (or any IMAP folder) instead of downloading + importing by hand. Each new
message's PDF attachment is run through the same ``import_statement`` pipeline
(balance-chain gate → uncategorized inbox), using the bank's PDF password.

Read-only on the mailbox: nothing is deleted or flagged. Idempotency comes from a
processed-Message-ID state file, and a message is only recorded once its import
actually succeeds, so a failed statement is retried next run.
"""

from __future__ import annotations

import email as emaillib
import imaplib
import json
import os
import ssl
import tempfile
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path

from finance.banks import load_bank
from finance.config import ensure_env_loaded, load_app_config
from finance.services.statement_import import import_statement


def _state_file() -> Path:
    return load_app_config().paths.state_dir / "email_fetch.json"


def _load_processed() -> dict:
    p = _state_file()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def _save_processed(state: dict) -> None:
    p = _state_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2))


def _decode(s: str | None) -> str:
    return str(make_header(decode_header(s or ""))).strip()


def _pdf_attachments(msg: Message) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        fn = part.get_filename()
        ctype = (part.get_content_type() or "").lower()
        if (fn and fn.lower().endswith(".pdf")) or ctype == "application/pdf":
            blob = part.get_payload(decode=True)
            if blob:
                out.append((_decode(fn) or "statement.pdf", blob))
    return out


def email_banks() -> list[str]:
    """Banks configured with an ingest.email block."""
    from finance.banks import list_banks

    return [b for b in list_banks() if load_bank(b).email]


def fetch_and_import(bank: str, *, dry_run: bool = False, ai_fallback: bool = False) -> dict:
    """Poll a bank's IMAP mailbox and import every new statement PDF found."""
    ensure_env_loaded()
    cfg = load_bank(bank)
    spec = cfg.email
    if not spec:
        raise ValueError(f"bank {bank!r} has no ingest.email config")

    host = spec.get("host", "imap.gmail.com")
    port = int(spec.get("port", 993))
    user_env = spec.get("user_env", "GMAIL_USER")
    pass_env = spec.get("password_env", "GMAIL_APP_PASSWORD")
    user = os.getenv(user_env)
    pw = os.getenv(pass_env)
    mailbox = spec.get("mailbox", "INBOX")
    account = spec.get("account") or cfg.account_names()[0]
    ai_fallback = ai_fallback or bool(spec.get("ai_fallback"))  # config can force AI (e.g. GoTyme)
    if not (user and pw):
        raise ValueError(f"missing IMAP credentials — set {user_env} and {pass_env} in your env/.env")

    state = _load_processed()
    done = set(state.get(bank, []))
    new_done: set[str] = set()
    files: list[dict] = []
    imported_total = 0
    scanned = 0

    conn = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
    try:
        conn.login(user, pw)
        typ, _ = conn.select(f'"{mailbox}"', readonly=True)
        if typ != "OK":
            raise ValueError(f"cannot open mailbox {mailbox!r} — check the label name")
        typ, data = conn.uid("SEARCH", None, "ALL")
        uids = data[0].split() if data and data[0] else []
        for uid in uids:
            typ, hd = conn.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
            msgid = ""
            if hd and hd[0]:
                msgid = (emaillib.message_from_bytes(hd[0][1]).get("Message-ID") or "").strip()
            if msgid and msgid in done:
                continue

            typ, raw = conn.uid("FETCH", uid, "(BODY.PEEK[])")
            if not (raw and raw[0]):
                continue
            msg = emaillib.message_from_bytes(raw[0][1])
            pdfs = _pdf_attachments(msg)
            if not pdfs:
                continue
            scanned += 1

            ok_all = True
            with tempfile.TemporaryDirectory() as td:
                for name, blob in pdfs:
                    fp = Path(td) / Path(name).name
                    fp.write_bytes(blob)
                    try:
                        res = import_statement(
                            fp, bank=bank, account=account,
                            profile=cfg.parse_profile(account),
                            dry_run=dry_run, ai_fallback=ai_fallback,
                        )
                        imported_total += res["inserted"]
                        files.append({
                            "file": name, "ok": True,
                            "inserted": res["inserted"],
                            "already": res["skipped_already_present"],
                            "verified": res["summary"].balance_chain_verified,
                        })
                    except Exception as exc:
                        ok_all = False
                        files.append({"file": name, "ok": False, "error": str(exc)})
            if ok_all and not dry_run and msgid:
                new_done.add(msgid)
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    if new_done and not dry_run:
        state[bank] = sorted(done | new_done)
        _save_processed(state)

    return {
        "bank": bank, "mailbox": mailbox, "scanned": scanned,
        "imported": imported_total, "files": files, "dry_run": dry_run,
    }
