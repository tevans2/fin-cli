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

from finance.statements.model import PasswordRequiredError, StatementFormatError, StatementRow
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


def _looks_like_password_error(exc: BaseException) -> bool:
    """True when pdfminer/pdfplumber failed because the PDF is encrypted.

    pdfplumber wraps the real error (e.g. PDFPasswordIncorrect) in a generic
    PdfminerException with an empty message, so walk the args + cause chain, not
    just the outer type/text.
    """
    parts: list[str] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    for _ in range(6):
        if cur is None or id(cur) in seen:
            break
        seen.add(id(cur))
        parts.append(type(cur).__name__)
        parts.append(str(cur))
        for a in getattr(cur, "args", ()):
            parts.append(type(a).__name__ if isinstance(a, BaseException) else str(a))
        cur = cur.__cause__ or cur.__context__
    blob = " ".join(parts).lower()
    return "password" in blob or "encrypt" in blob


def extract_lines(
    path: Path,
    password: str | None = None,
    *,
    x_tolerance: float | None = None,
    y_tolerance: float | None = None,
) -> list[str]:
    """Extract text lines from a PDF.

    ``y_tolerance`` controls how far apart (in points) characters can be
    vertically and still count as the same line. Some banks (e.g. GoTyme) draw
    overlapping/pending rows a couple of points apart; the default of 3 merges
    them into garbled text, so a tighter value (1) separates them.
    """
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise StatementFormatError("PDF import needs pdfplumber (pip install -e '.[dev]' or the base deps)") from exc

    try:
        pdf = pdfplumber.open(str(path), password=password or "")
    except Exception as exc:
        if _looks_like_password_error(exc):
            raise PasswordRequiredError(
                "wrong password" if password else "PDF is password-protected"
            ) from exc
        raise StatementFormatError(f"Could not open PDF: {exc or type(exc).__name__}") from exc

    kwargs = {}
    if x_tolerance is not None:
        kwargs["x_tolerance"] = x_tolerance
    if y_tolerance is not None:
        kwargs["y_tolerance"] = y_tolerance

    lines: list[str] = []
    with pdf:
        for page in pdf.pages:
            text = page.extract_text(**kwargs) or ""
            lines.extend(line.strip() for line in text.splitlines() if line.strip())
    return lines


def parse_pdf(
    path: Path, profile: StatementProfile, password: str | None = None
) -> tuple[list[StatementRow], str | None]:
    settings = profile.pdf or {}
    lines = extract_lines(
        Path(path),
        password=password,
        x_tolerance=settings.get("x_tolerance"),
        y_tolerance=settings.get("y_tolerance"),
    )
    return rows_from_lines(lines, profile), None
