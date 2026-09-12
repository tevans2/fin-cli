"""OpenAI fallback for PDF statements the deterministic parser can't handle.

This is a last resort: when a PDF has no working ``pdf.line_regex`` or the parsed
rows fail the balance chain, the statement text is sent to OpenAI to extract
transactions. The extracted rows are then run back through the same balance chain
by the caller, so an AI extraction is only trusted when it actually reconciles.

Privacy: this sends statement text to OpenAI, an external service. It only runs
when explicitly enabled (``fin import ... --ai-fallback``) and needs
``OPENAI_API_KEY``. The model is set with ``OPENAI_MODEL`` (default gpt-4o-mini).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from finance.statements.model import StatementFormatError, StatementRow
from finance.statements.normalize import parse_date, to_decimal
from finance.statements.profile import StatementProfile

DEFAULT_MODEL = "gpt-4o-mini"
MAX_CHARS = 120_000  # guardrail against enormous PDFs blowing the context/budget

_SYSTEM_PROMPT = (
    "You extract transactions from raw bank-statement text. "
    "You return ONLY a JSON object and never invent transactions that are not present."
)

_USER_TEMPLATE = """Extract every transaction from this bank statement.

Return a JSON object of exactly this shape:
{{"transactions": [
  {{"date": "YYYY-MM-DD", "description": "text", "amount": "-123.45", "balance": "1000.00"}}
]}}

Rules:
- One object per transaction, in chronological order (oldest first).
- date: ISO YYYY-MM-DD.
- amount: a decimal string; NEGATIVE for money out (debit), POSITIVE for money in (credit).
- balance: the running account balance after the transaction as a decimal string,
  or null if the statement does not show a per-line balance. Include it whenever present —
  it is used to verify the extraction.
- Do not include opening/closing summary lines as transactions.
- The account currency is {currency}.

Statement text:
---
{text}
---"""


def extract_pdf_text(path: Path, password: str | None = None) -> str:
    from finance.statements.pdf_parser import extract_lines

    return "\n".join(extract_lines(Path(path), password=password))


def rows_from_ai_payload(payload: dict, profile: StatementProfile) -> list[StatementRow]:
    """Convert the model's JSON payload into StatementRows (pure, testable)."""
    transactions = payload.get("transactions")
    if not isinstance(transactions, list) or not transactions:
        raise StatementFormatError("AI extraction returned no transactions")

    formats = list(dict.fromkeys([*profile.date_formats, "%Y-%m-%d"]))
    rows: list[StatementRow] = []
    for index, txn in enumerate(transactions, start=1):
        if not isinstance(txn, dict):
            raise StatementFormatError(f"AI transaction #{index} is not an object")
        description = " ".join(str(txn.get("description") or "").split())
        if not description:
            raise StatementFormatError(f"AI transaction #{index} has no description")
        if txn.get("amount") in (None, ""):
            raise StatementFormatError(f"AI transaction #{index} has no amount")
        raw_balance = txn.get("balance")
        balance = None
        if raw_balance not in (None, "", "null"):
            balance = f"{to_decimal(str(raw_balance)):.2f}"
        rows.append(
            StatementRow(
                date=parse_date(str(txn.get("date", "")), formats),
                description=description,
                amount=f"{to_decimal(str(txn['amount'])):.2f}",
                balance=balance,
                line_number=index,
                raw={"ai": json.dumps(txn, ensure_ascii=False)},
            )
        )
    return rows


def _call_openai(text: str, *, currency: str, model: str) -> dict:
    from finance.config import ensure_env_loaded

    ensure_env_loaded()  # pick up OPENAI_API_KEY from ./.env or FIN_DATA_DIR/config/.env
    if not os.getenv("OPENAI_API_KEY"):
        raise StatementFormatError(
            "AI fallback needs OPENAI_API_KEY — set it in your environment, ./.env, "
            "or FIN_DATA_DIR/config/.env"
        )
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise StatementFormatError("AI fallback needs the openai package: pip install -e '.[ai]'") from exc

    client = OpenAI()
    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        temperature=0,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _USER_TEMPLATE.format(currency=currency, text=text[:MAX_CHARS])},
        ],
    )
    content = response.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise StatementFormatError(f"AI returned invalid JSON: {exc}") from exc


def extract_pdf_rows(
    path: Path, profile: StatementProfile, *, reason: str = "", password: str | None = None
) -> list[StatementRow]:
    """Extract transactions from a PDF via OpenAI (deterministic parse having failed)."""
    from finance.config import ensure_env_loaded

    ensure_env_loaded()
    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    text = extract_pdf_text(Path(path), password=password)
    if not text.strip():
        raise StatementFormatError("Could not extract any text from the PDF to send to the AI")
    print(f"PDF parse failed ({reason}); sending statement text to OpenAI ({model}) to extract transactions…")
    payload = _call_openai(text, currency=profile.currency, model=model)
    rows = rows_from_ai_payload(payload, profile)
    print(f"AI returned {len(rows)} transaction(s); validating against the balance chain…")
    return rows
