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
from decimal import Decimal
from pathlib import Path

from finance.statements.model import BalanceChainError, StatementFormatError, StatementRow
from finance.statements.normalize import parse_date, to_decimal
from finance.statements.profile import StatementProfile

MAX_CHARS = 120_000  # guardrail against enormous PDFs blowing the context/budget

_SYSTEM_PROMPT = (
    "You extract transactions from raw bank-statement text. "
    "You return ONLY a JSON object and never invent transactions that are not present."
)

_USER_TEMPLATE = """Extract every transaction from this bank statement.

Return a JSON object of exactly this shape:
{{"opening_balance": "1000.00", "closing_balance": "1234.56",
  "total_credit": "500.00", "total_debit": "265.44",
  "transactions": [
    {{"date": "YYYY-MM-DD", "description": "text", "amount": "-123.45", "balance": "1000.00"}}
  ]}}

Rules:
- opening_balance / closing_balance / total_credit / total_debit: copy these from
  the statement's summary section if it shows them, else null. Read them carefully —
  they are used to verify the extraction.
- One object per transaction, in chronological order (oldest first).
- date: ISO YYYY-MM-DD.
- balance: THE MOST IMPORTANT FIELD. Copy verbatim the number in the statement's
  rightmost "Running Balance" column for that exact row — the last number on the
  row. Do NOT calculate or infer it; transcribe exactly what is printed. If (and
  only if) the statement has no per-row running-balance column, use null.
- amount: your best signed decimal — NEGATIVE for money out, POSITIVE for money in.
  Don't agonise over the sign: when a running balance is present the sign is
  recomputed from the change in balance, so just transcribe the balances faithfully.
- A transaction may span multiple lines: the description can wrap onto the line
  above or below, and a long reference number often sits on its own line. Merge
  these into one transaction; ignore stray one- or two-character fragments (page
  watermarks bleeding into rows).
- Do not include opening/closing summary lines or column headers as transactions.
- The account currency is {currency}.

Statement text:
---
{text}
---"""


def extract_pdf_text(
    path: Path,
    password: str | None = None,
    *,
    x_tolerance: float | None = None,
    y_tolerance: float | None = 1,
) -> str:
    """Extract PDF text for the AI.

    Defaults to a tight ``y_tolerance`` so banks that draw overlapping/pending
    rows (e.g. GoTyme) come through as separate lines instead of merged garble;
    the AI ignores the short watermark fragments this can leave behind.
    """
    from finance.statements.pdf_parser import extract_lines

    return "\n".join(
        extract_lines(Path(path), password=password, x_tolerance=x_tolerance, y_tolerance=y_tolerance)
    )


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


def _opt_decimal(value) -> Decimal | None:
    if value in (None, "", "null"):
        return None
    return to_decimal(str(value))


def reconcile_with_balances(payload: dict, rows: list[StatementRow]) -> list[StatementRow]:
    """Correct amounts from the authoritative running-balance column, then validate.

    The credit/debit sign is ambiguous in flattened statement text (descriptions
    contain dashes; the model guesses from wording), but the running balance is
    reliable. When every row has a balance and the statement's opening balance is
    known, the true amount of each row is ``balance - previous balance``. Because
    that makes the balance chain pass by construction, the extraction is instead
    validated against the statement's own printed summary totals.

    Returns rows unchanged when balances/opening aren't all available (the caller
    then falls back to validating the model's own amounts via the balance chain).
    """
    opening = _opt_decimal(payload.get("opening_balance"))
    if opening is None or not all(r.balance is not None for r in rows):
        return rows

    prev = opening
    for row in rows:
        current = Decimal(row.balance)  # type: ignore[arg-type]
        row.amount = f"{current - prev:.2f}"
        prev = current

    net = sum((Decimal(r.amount) for r in rows), Decimal(0))
    credits = sum((Decimal(r.amount) for r in rows if Decimal(r.amount) > 0), Decimal(0))
    debits = -sum((Decimal(r.amount) for r in rows if Decimal(r.amount) < 0), Decimal(0))

    problems: list[str] = []
    closing = _opt_decimal(payload.get("closing_balance"))
    if closing is not None and opening + net != closing:
        problems.append(f"opening+net = {opening + net} but statement closing = {closing}")
    total_credit = _opt_decimal(payload.get("total_credit"))
    if total_credit is not None and credits != total_credit:
        problems.append(f"credits total {credits} != statement total credit {total_credit}")
    total_debit = _opt_decimal(payload.get("total_debit"))
    if total_debit is not None and debits != total_debit:
        problems.append(f"debits total {debits} != statement total debit {total_debit}")
    if problems:
        raise BalanceChainError(
            "AI extraction disagrees with the statement's printed summary: " + "; ".join(problems)
        )
    return rows


def _call_openai(text: str, *, currency: str, model: str, temperature: float = 0) -> dict:
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
        temperature=temperature,
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
    """Extract transactions from a PDF via OpenAI (deterministic parse having failed).

    A single misread digit fails the summary validation, so we retry a few times
    with a little temperature and accept the first extraction that reconciles —
    the validation is strict (it must match the statement's printed totals), so a
    passing result is trustworthy.
    """
    from finance import settings
    from finance.config import ensure_env_loaded

    ensure_env_loaded()
    model = settings.get("openai_model")
    attempts = max(1, int(settings.get("ai_attempts")))
    pdf_settings = profile.pdf or {}
    text = extract_pdf_text(
        Path(path),
        password=password,
        x_tolerance=pdf_settings.get("x_tolerance"),
        y_tolerance=pdf_settings.get("y_tolerance", 1),
    )
    if not text.strip():
        raise StatementFormatError("Could not extract any text from the PDF to send to the AI")
    print(f"PDF parse failed ({reason}); sending statement text to OpenAI ({model}) to extract transactions…")

    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        payload = _call_openai(
            text, currency=profile.currency, model=model, temperature=0 if attempt == 1 else 0.4
        )
        try:
            rows = reconcile_with_balances(payload, rows_from_ai_payload(payload, profile))
        except (BalanceChainError, StatementFormatError) as exc:
            last_exc = exc
            if attempt < attempts:
                print(f"  attempt {attempt} didn't reconcile ({exc}); retrying…")
                continue
            raise
        print(f"AI returned {len(rows)} transaction(s) (attempt {attempt}); validating against the balance chain…")
        return rows
    raise last_exc or StatementFormatError("AI extraction failed")  # pragma: no cover
