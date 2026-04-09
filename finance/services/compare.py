from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import csv
import io
import subprocess

from finance.config import load_app_config
from finance.models.transaction import TransactionRecord
from finance.providers.investec import InvestecProvider
from finance.services.transactions import load_bank_transactions


@dataclass
class CompareRow:
    side: str
    date: str
    amount: str
    currency: str
    label: str
    txn_id: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.date, self.amount, self.label)


@dataclass
class CompareDataset:
    bank: str
    account: str
    date_mode: str
    start_date: str
    end_date: str
    api_rows: list[CompareRow]
    journal_rows: list[CompareRow]
    api_current_balance: str | None = None
    api_available_balance: str | None = None
    balance_currency: str = "ZAR"
    journal_balance: str | None = None
    journal_balance_label: str | None = None


def determine_compare_range(begin: str | None = None, end: str | None = None, days: int = 30) -> tuple[str, str]:
    end_date = end or datetime.now().strftime("%Y-%m-%d")
    if begin:
        return begin, end_date
    start = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end_date


def _record_label(record: TransactionRecord) -> str:
    return record.alias or record.payee or record.description


def load_journal_side(bank: str, account: str, begin: str, end: str) -> list[CompareRow]:
    rows: list[CompareRow] = []
    for record in load_bank_transactions(bank):
        if record.source_account != account:
            continue
        if begin <= record.date <= end:
            rows.append(
                CompareRow(
                    side="journal",
                    date=record.date,
                    amount=record.amount,
                    currency=record.currency,
                    label=_record_label(record),
                    txn_id=record.id,
                )
            )
    return sorted(rows, key=lambda r: (r.date, r.txn_id))


def load_api_side(bank: str, account: str, begin: str, end: str, date_mode: str) -> list[CompareRow]:
    config = load_app_config()
    bank_config = config.banks.get("banks", {}).get(bank)
    if not bank_config:
        raise ValueError(f"Bank not configured: {bank}")
    if bank != "investec":
        raise ValueError("Compare currently supports investec only")

    provider = InvestecProvider(bank_config, account_name=account)
    fetched = provider.fetch_transactions(
        begin,
        end,
        date_mode=date_mode,
        record_date_mode=date_mode,
    )
    rows = [
        CompareRow(
            side="api",
            date=item.date,
            amount=item.amount,
            currency=item.currency,
            label=item.payee or item.description,
            txn_id=item.id,
        )
        for item in fetched
    ]
    return sorted(rows, key=lambda r: (r.date, r.txn_id))


def _default_compare_date_mode(account: str) -> str:
    return "action" if account == "savings" else "posting"


def _resolve_ledger_account(bank: str, bank_config: dict, account: str) -> str:
    accounts = bank_config.get("accounts", {})
    if account in accounts and accounts[account].get("ledger_account"):
        return accounts[account]["ledger_account"]

    configured = bank_config.get("ledger_account")
    configured_type = bank_config.get("type")
    if configured and account == configured_type:
        return configured
    if configured and configured.endswith(":checking") and account == "savings":
        return configured[:-len(":checking")] + ":savings"
    if configured and configured_type and configured.endswith(f":{configured_type}"):
        return configured[: -len(configured_type)] + account
    return f"assets:bank:{bank}:{account}"


def load_api_balance(bank: str, account: str) -> dict:
    config = load_app_config()
    bank_config = config.banks.get("banks", {}).get(bank)
    if not bank_config:
        raise ValueError(f"Bank not configured: {bank}")
    provider = InvestecProvider(bank_config, account_name=account)
    return provider.fetch_balance()


def load_journal_balance(bank: str, account: str, end_date: str) -> tuple[str | None, str]:
    config = load_app_config()
    bank_config = config.banks.get("banks", {}).get(bank)
    if not bank_config:
        raise ValueError(f"Bank not configured: {bank}")
    ledger_account = _resolve_ledger_account(bank, bank_config, account)
    exclusive_end = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    cmd = [
        "hledger",
        "--no-conf",
        "-f",
        str(config.paths.main_journal),
        "balance",
        ledger_account,
        "-e",
        exclusive_end,
        "-O",
        "csv",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None, ledger_account

    rows = list(csv.reader(io.StringIO(result.stdout)))
    if len(rows) < 2 or len(rows[1]) < 2:
        return None, ledger_account
    return rows[1][1], ledger_account


def build_compare_dataset(
    bank: str,
    account: str = "checking",
    begin: str | None = None,
    end: str | None = None,
    days: int = 30,
    date_mode: str | None = None,
) -> CompareDataset:
    start_date, end_date = determine_compare_range(begin, end, days)
    effective_date_mode = date_mode or _default_compare_date_mode(account)
    api_balance = load_api_balance(bank, account)
    journal_balance, ledger_account = load_journal_balance(bank, account, end_date)
    return CompareDataset(
        bank=bank,
        account=account,
        date_mode=effective_date_mode,
        start_date=start_date,
        end_date=end_date,
        api_rows=load_api_side(bank, account, start_date, end_date, effective_date_mode),
        journal_rows=load_journal_side(bank, account, start_date, end_date),
        api_current_balance=api_balance.get("current_balance"),
        api_available_balance=api_balance.get("available_balance"),
        balance_currency=api_balance.get("currency", "ZAR"),
        journal_balance=journal_balance,
        journal_balance_label=ledger_account,
    )
