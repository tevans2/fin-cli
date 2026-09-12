from __future__ import annotations

from pathlib import Path

from finance.statements.balance import can_verify, summarize, verify_balance_chain
from finance.statements.csv_parser import parse_csv
from finance.statements.model import (
    BalanceChainError,
    StatementFormatError,
    StatementRow,
    StatementSummary,
)
from finance.statements.profile import StatementProfile


def format_breaks(breaks: list[dict]) -> str:
    detail = "; ".join(
        f"line {b['line']} ({b['date']} {b['description']}): "
        f"expected {b['expected_balance']}, got {b['actual_balance']}"
        for b in breaks[:5]
    )
    more = "" if len(breaks) <= 5 else f" (+{len(breaks) - 5} more)"
    return f"Statement running balance is inconsistent at {len(breaks)} row(s): {detail}{more}"


def parse_statement(path: str | Path, profile: StatementProfile) -> tuple[list[StatementRow], StatementSummary]:
    """Parse a statement file and run the balance-chain accuracy gate.

    Returns chronologically ordered rows plus a summary. Raises
    :class:`BalanceChainError` if the running balance does not reconcile, which
    means a row was misread, dropped, or duplicated.
    """
    path = Path(path)
    if profile.format == "csv":
        rows, account_name = parse_csv(path, profile)
    elif profile.format == "pdf":
        from finance.statements.pdf_parser import parse_pdf

        rows, account_name = parse_pdf(path, profile)
    else:
        raise StatementFormatError(f"Unknown statement format: {profile.format!r}")

    verified = False
    if can_verify(rows):
        breaks = verify_balance_chain(rows)
        if breaks:
            raise BalanceChainError(format_breaks(breaks))
        verified = True
    elif profile.require_balance_chain:
        raise BalanceChainError(
            "Profile requires balance-chain verification, but not every row has a balance column value"
        )

    return rows, summarize(rows, verified=verified, account_name=account_name)
