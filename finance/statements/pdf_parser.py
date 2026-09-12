"""PDF statement parsing.

Generic PDF table detection is unreliable across banks, so a PDF profile drives
parsing with a per-line regex (``pdf.line_regex``) whose named groups map onto
statement fields. The balance chain (run by ``parse_statement``) then catches any
misread or dropped line, which is what makes PDF parsing trustworthy rather than
hopeful.

Recognised named groups: ``date`` (required), ``description`` (required),
``amount`` and optional ``direction`` (Cr/Dr/+/-), or ``debit``/``credit``, plus
optional ``balance``, ``action_date`` and ``reference``.
"""

from __future__ import annotations

from pathlib import Path

from finance.statements.model import StatementFormatError, StatementRow
from finance.statements.normalize import parse_date, to_decimal
from finance.statements.profile import StatementProfile

_DEBIT_MARKERS = {"dr", "debit", "-"}
_CREDIT_MARKERS = {"cr", "credit", "+"}


def _amount_from_groups(groups: dict[str, str | None], line_number: int) -> str:
    amount = groups.get("amount")
    if amount not in (None, ""):
        value = to_decimal(amount)
        direction = (groups.get("direction") or "").strip().lower()
        if direction in _DEBIT_MARKERS:
            value = -abs(value)
        elif direction in _CREDIT_MARKERS:
            value = abs(value)
        return f"{value:.2f}"
    debit = to_decimal(groups.get("debit"))
    credit = to_decimal(groups.get("credit"))
    if debit and credit:
        raise StatementFormatError(f"PDF line {line_number}: matched both a debit and a credit")
    if not debit and not credit:
        raise StatementFormatError(f"PDF line {line_number}: matched neither a debit nor a credit")
    return f"{credit - debit:.2f}"


def rows_from_lines(lines: list[str], profile: StatementProfile) -> list[StatementRow]:
    """Turn extracted text lines into StatementRows using the profile's line regex.

    Pure and side-effect free, so it can be tested without a real PDF.
    """
    import re

    settings = profile.pdf or {}
    pattern = settings.get("line_regex")
    if not pattern:
        raise StatementFormatError(
            "PDF profile needs a `pdf.line_regex` with named groups "
            "(date, description, amount[, direction, balance, reference]). "
            "See docs/statement-import.md."
        )
    regex = re.compile(pattern)

    rows: list[StatementRow] = []
    for number, line in enumerate(lines, start=1):
        match = regex.search(line)
        if not match:
            continue
        groups = match.groupdict()
        if "date" not in groups or "description" not in groups:
            raise StatementFormatError("pdf.line_regex must define at least `date` and `description` groups")
        description = " ".join((groups.get("description") or "").split())
        if not description:
            continue
        balance = None
        if groups.get("balance") not in (None, ""):
            balance = f"{to_decimal(groups['balance']):.2f}"
        action_date = None
        if groups.get("action_date") not in (None, ""):
            action_date = parse_date(groups["action_date"], profile.date_formats)  # type: ignore[arg-type]
        reference = (groups.get("reference") or "").strip() or None
        rows.append(
            StatementRow(
                date=parse_date(groups["date"], profile.date_formats),  # type: ignore[arg-type]
                description=description,
                amount=_amount_from_groups(groups, number),
                balance=balance,
                reference=reference,
                action_date=action_date,
                line_number=number,
                raw={"line": line},
            )
        )

    if not rows:
        raise StatementFormatError(
            "pdf.line_regex matched no transaction lines — check the pattern against the PDF text"
        )
    if profile.order == "newest_first":
        rows.reverse()
    return rows


def extract_lines(path: Path, password: str | None = None) -> list[str]:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise StatementFormatError("PDF import needs pdfplumber (pip install -e '.[dev]' or the base deps)") from exc

    try:
        pdf = pdfplumber.open(str(path), password=password or "")
    except Exception as exc:
        hint = (
            "wrong password"
            if password
            else "it may be password-protected — set <BANK>_DOC_CODE in your environment or .env"
        )
        raise StatementFormatError(f"Could not open PDF ({hint}): {exc}") from exc

    lines: list[str] = []
    with pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines.extend(line.strip() for line in text.splitlines() if line.strip())
    return lines


def parse_pdf(
    path: Path, profile: StatementProfile, password: str | None = None
) -> tuple[list[StatementRow], str | None]:
    return rows_from_lines(extract_lines(Path(path), password=password), profile), None
