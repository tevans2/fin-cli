from __future__ import annotations

from finance.config import load_app_config


def resolve_ledger_account(bank: str, account: str) -> str:
    """The hledger asset account a bank/account maps to.

    Honours an explicit ``accounts.<name>.ledger_account`` in banks.yaml, then
    falls back to deriving from the bank's configured default account, then to a
    conventional ``assets:bank:<bank>:<account>``.
    """
    config = load_app_config()
    bank_config = config.banks.get("banks", {}).get(bank, {})

    accounts = bank_config.get("accounts", {})
    if account in accounts and accounts[account].get("ledger_account"):
        return accounts[account]["ledger_account"]

    configured = bank_config.get("ledger_account")
    configured_type = bank_config.get("type")
    if configured and account == configured_type:
        return configured
    if configured and configured.endswith(":checking") and account == "savings":
        return configured[: -len(":checking")] + ":savings"
    if configured and configured_type and configured.endswith(f":{configured_type}"):
        return configured[: -len(configured_type)] + account
    return f"assets:bank:{bank}:{account}"
