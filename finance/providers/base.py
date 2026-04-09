from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from finance.models.transaction import TransactionRecord


@dataclass
class FetchedTransaction:
    id: str
    source_account: str
    date: str
    description: str
    amount: str
    currency: str
    status: str
    payee: str | None = None
    source_hash: str | None = None
    provider_metadata: dict | None = None


class Provider(Protocol):
    name: str

    def fetch_transactions(
        self,
        start_date: str,
        end_date: str,
        date_mode: str = "action",
        record_date_mode: str = "posting",
    ) -> list[FetchedTransaction]:
        ...
