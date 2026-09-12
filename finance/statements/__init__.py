"""Statement import framework.

Parsing a statement file (CSV or PDF) and ingesting it into canonical storage
are separate concerns:

- ``parse`` turns a file into a list of normalized :class:`StatementRow` objects,
  driven by a :class:`StatementProfile` so onboarding a new no-API account is a
  config task, not a code change.
- the running-balance chain (:func:`verify_balance_chain`) is a universal
  accuracy gate: any statement that carries a balance column is checked, and a
  broken chain proves a row was misread, dropped, or duplicated.
- one ingest service (``finance.services.statement_import``) consumes the rows
  for every bank.
"""

from finance.statements.balance import (
    opening_balance,
    summarize,
    verify_balance_chain,
)
from finance.statements.model import (
    BalanceChainError,
    StatementFormatError,
    StatementRow,
    StatementSummary,
)
from finance.statements.profile import StatementProfile, load_profile

__all__ = [
    "StatementRow",
    "StatementSummary",
    "StatementFormatError",
    "BalanceChainError",
    "StatementProfile",
    "load_profile",
    "verify_balance_chain",
    "opening_balance",
    "summarize",
]
