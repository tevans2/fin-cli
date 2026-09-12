from __future__ import annotations

from decimal import Decimal

from finance.statements.model import StatementRow, StatementSummary


def _all_have_balance(rows: list[StatementRow]) -> bool:
    return bool(rows) and all(r.balance is not None for r in rows)


def verify_balance_chain(rows: list[StatementRow]) -> list[dict]:
    """Check every row's balance against the previous balance + this amount.

    ``rows`` must be in chronological order. Returns a list of breaks; an empty
    list means the statement reconciles, which also proves no row was duplicated,
    dropped, or misread. Rows without a balance are skipped (an all-or-nothing
    check is enforced by the caller via :func:`can_verify`).
    """
    breaks: list[dict] = []
    for previous, current in zip(rows, rows[1:], strict=False):
        if previous.balance is None or current.balance is None:
            continue
        expected = previous.balance_decimal + current.amount_decimal  # type: ignore[operator]
        actual = current.balance_decimal
        if expected != actual:
            breaks.append(
                {
                    "line": current.line_number,
                    "date": current.date,
                    "description": current.description,
                    "expected_balance": f"{expected:.2f}",
                    "actual_balance": f"{actual:.2f}",
                    "difference": f"{actual - expected:.2f}",  # type: ignore[operator]
                }
            )
    return breaks


def can_verify(rows: list[StatementRow]) -> bool:
    """True when every row carries a balance, so the chain can be checked."""
    return _all_have_balance(rows)


def opening_balance(rows: list[StatementRow]) -> str | None:
    """Balance immediately before the first (chronological) row."""
    if not rows or rows[0].balance is None:
        return None
    return f"{rows[0].balance_decimal - rows[0].amount_decimal:.2f}"  # type: ignore[operator]


def summarize(rows: list[StatementRow], *, verified: bool, account_name: str | None = None) -> StatementSummary:
    debits = sum((r.amount_decimal for r in rows if r.amount_decimal < 0), Decimal(0))
    credits = sum((r.amount_decimal for r in rows if r.amount_decimal > 0), Decimal(0))
    closing = rows[-1].balance if rows else None
    return StatementSummary(
        rows=len(rows),
        date_range={"start": rows[0].date, "end": rows[-1].date} if rows else None,
        opening_balance=opening_balance(rows),
        closing_balance=closing,
        total_debits=f"{debits:.2f}",
        total_credits=f"{credits:.2f}",
        balance_chain_verified=verified,
        account_name=account_name,
    )
