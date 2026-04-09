from __future__ import annotations

import hashlib
import os
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal

import requests

from finance.providers.base import FetchedTransaction


class InvestecProvider:
    name = "investec"

    def __init__(self, bank_config: dict, account_name: str | None = None):
        self.bank_config = bank_config
        self.account_name = account_name or bank_config.get("type") or "checking"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "finance-v2/0.1", "Accept": "application/json"})

    def _credentials(self) -> dict[str, str]:
        account_env_key = f"INVESTEC_{self.account_name.upper()}_ACCOUNT_ID"
        account_id = os.getenv(account_env_key, "") or os.getenv("INVESTEC_ACCOUNT_ID", "")
        required = {
            "client_id": os.getenv("INVESTEC_CLIENT_ID", ""),
            "client_secret": os.getenv("INVESTEC_CLIENT_SECRET", ""),
            "api_key": os.getenv("INVESTEC_API_KEY", ""),
            "account_id": account_id,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(
                f"Missing Investec credentials for account '{self.account_name}': {', '.join(missing)}"
            )
        return required

    def authenticate(self) -> None:
        creds = self._credentials()
        timeout = self.bank_config.get("api", {}).get("timeout_seconds", 30)
        response = self.session.post(
            "https://openapi.investec.com/identity/v2/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(creds["client_id"], creds["client_secret"]),
            headers={
                "x-api-key": creds["api_key"],
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise ValueError("Investec auth response did not include access_token")
        self.session.headers["Authorization"] = f"Bearer {token}"

    def fetch_balance(self) -> dict:
        creds = self._credentials()
        self.authenticate()
        timeout = self.bank_config.get("api", {}).get("timeout_seconds", 30)
        response = self.session.get(
            f"https://openapi.investec.com/za/pb/v1/accounts/{creds['account_id']}/balance",
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json().get("data", {})
        return {
            "current_balance": f"{Decimal(str(data.get('currentBalance', 0))):.2f}",
            "available_balance": f"{Decimal(str(data.get('availableBalance', 0))):.2f}",
            "currency": data.get("currency", self.bank_config.get("default_currency", "ZAR")),
        }

    def fetch_raw_transactions(self) -> list[dict]:
        creds = self._credentials()
        self.authenticate()
        timeout = self.bank_config.get("api", {}).get("timeout_seconds", 30)
        response = self.session.get(
            f"https://openapi.investec.com/za/pb/v1/accounts/{creds['account_id']}/transactions",
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json().get("data", {}).get("transactions", [])

    def fetch_transactions(
        self,
        start_date: str,
        end_date: str,
        date_mode: str = "action",
        record_date_mode: str = "posting",
    ) -> list[FetchedTransaction]:
        raw_transactions = self.fetch_raw_transactions()

        rows: list[FetchedTransaction] = []
        for txn in raw_transactions:
            posting_date = txn.get("postingDate", "")
            action_date = txn.get("actionDate") or posting_date
            filter_date = posting_date if date_mode == "posting" else action_date
            record_date = posting_date if record_date_mode == "posting" else action_date
            if not posting_date or not filter_date or filter_date < start_date or filter_date > end_date:
                continue

            amount = float(txn.get("amount", 0))
            if txn.get("type") == "DEBIT":
                amount = -amount

            txn_id = txn.get("uuid") or self._fallback_id(posting_date, amount, txn.get("description", ""))
            rows.append(
                FetchedTransaction(
                    id=txn_id,
                    source_account=self.account_name,
                    date=record_date,
                    description=(txn.get("description") or "").strip(),
                    amount=f"{amount:.2f}",
                    currency="ZAR",
                    status="pending" if txn.get("status", "POSTED").upper() == "PENDING" else "cleared",
                    payee=(txn.get("description") or "").strip() or None,
                    source_hash=hashlib.sha256(repr(sorted(txn.items())).encode()).hexdigest()[:16],
                    provider_metadata={
                        "provider_status": txn.get("status"),
                        "posting_date": posting_date,
                        "action_date": action_date,
                        "fetched_at": datetime.utcnow().isoformat() + "Z",
                    },
                )
            )
        return rows

    @staticmethod
    def _fallback_id(date: str, amount: float, description: str) -> str:
        return hashlib.sha256(f"{date}|{amount:.2f}|{description}".encode()).hexdigest()[:16]
