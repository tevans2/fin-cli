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


def _spec(bank: str):
    ensure_env_loaded()
    cfg = load_bank(bank)
    if not cfg.email:
        raise ValueError(f"bank {bank!r} has no ingest.email config")
    return cfg, cfg.email


def _connect(spec: dict):
    user_env = spec.get("user_env", "GMAIL_USER")
    pass_env = spec.get("password_env", "GMAIL_APP_PASSWORD")
    user, pw = os.getenv(user_env), os.getenv(pass_env)
    if not (user and pw):
        raise ValueError(f"missing IMAP credentials — set {user_env} and {pass_env} in your env/.env")
    conn = imaplib.IMAP4_SSL(spec.get("host", "imap.gmail.com"), int(spec.get("port", 993)),
                             ssl_context=ssl.create_default_context())
    conn.login(user, pw)
    typ, _ = conn.select(f'''"{spec.get("mailbox", "INBOX")}"''', readonly=True)
    if typ != "OK":
        conn.logout()
        raise ValueError(f"cannot open mailbox {spec.get('mailbox', 'INBOX')!r} — check the label name")
    return conn


def list_pending(bank: str) -> dict:
    """New (not-yet-imported) statement messages in the bank's mailbox."""
    _cfg, spec = _spec(bank)
    done = set(_load_processed().get(bank, []))
    mailbox = spec.get("mailbox", "INBOX")
    messages: list[dict] = []
    conn = _connect(spec)
    try:
        typ, data = conn.uid("SEARCH", None, "ALL")
        for uid in (data[0].split() if data and data[0] else []):
            typ, raw = conn.uid("FETCH", uid, "(BODY.PEEK[])")
            if not (raw and raw[0]):
                continue
            msg = emaillib.message_from_bytes(raw[0][1])
            msgid = (msg.get("Message-ID") or "").strip()
            if msgid and msgid in done:
                continue
            pdfs = _pdf_attachments(msg)
            if not pdfs:
                continue
            messages.append({"bank": bank, "msgid": msgid,
                             "subject": _decode(msg.get("Subject", "")), "filename": pdfs[0][0]})
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return {"bank": bank, "mailbox": mailbox, "messages": messages}


def import_one(bank: str, msgid: str, *, dry_run: bool = False, ai_fallback: bool = False) -> dict:
    """Import the statement PDF from a single message (by Message-ID)."""
    cfg, spec = _spec(bank)
    account = spec.get("account") or cfg.account_names()[0]
    ai = ai_fallback or bool(spec.get("ai_fallback"))
    result = {"bank": bank, "msgid": msgid, "file": None, "ok": False,
              "inserted": 0, "already": 0, "verified": False, "error": None}
    conn = _connect(spec)
    try:
        typ, data = conn.uid("SEARCH", None, "HEADER", "Message-ID", f'"{msgid}"')
        uids = data[0].split() if data and data[0] else []
        if not uids:
            result["error"] = "message not found"
            return result
        typ, raw = conn.uid("FETCH", uids[0], "(BODY.PEEK[])")
        msg = emaillib.message_from_bytes(raw[0][1])
        pdfs = _pdf_attachments(msg)
        if not pdfs:
            result["error"] = "no PDF attachment"
            return result
        name, blob = pdfs[0]
        result["file"] = name
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / Path(name).name
            fp.write_bytes(blob)
            try:
                res = import_statement(fp, bank=bank, account=account,
                                       profile=cfg.parse_profile(account),
                                       dry_run=dry_run, ai_fallback=ai)
                result.update(ok=True, inserted=res["inserted"],
                              already=res["skipped_already_present"],
                              verified=res["summary"].balance_chain_verified)
            except Exception as exc:
                result["error"] = str(exc)
        if result["ok"] and not dry_run and msgid:
            state = _load_processed()
            state[bank] = sorted(set(state.get(bank, [])) | {msgid})
            _save_processed(state)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return result


def fetch_and_import(bank: str, *, dry_run: bool = False, ai_fallback: bool = False,
                     progress=None) -> dict:
    """Poll a bank's IMAP mailbox and import every new statement PDF found.

    ``progress`` is an optional ``callable(str)`` that receives human-readable
    stage messages ("connecting…", "found N…", "importing X (i/N)…").
    """
    def emit(msg: str) -> None:
        if progress:
            progress(msg)

    cfg, spec = _spec(bank)
    emit(f"connecting to {spec.get('mailbox', 'INBOX')}")
    pending = list_pending(bank)
    msgs = pending["messages"]
    emit(f"found {len(msgs)} new statement(s)")

    files: list[dict] = []
    imported = 0
    for i, row in enumerate(msgs, 1):
        emit(f"importing {row['filename']} ({i}/{len(msgs)})")
        r = import_one(bank, row["msgid"], dry_run=dry_run, ai_fallback=ai_fallback)
        files.append({k: r[k] for k in ("file", "ok", "inserted", "already", "verified", "error")})
        imported += r["inserted"]
    emit("done")
    return {"bank": bank, "mailbox": pending["mailbox"], "scanned": len(msgs),
            "imported": imported, "files": files, "dry_run": dry_run}
