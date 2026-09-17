"""Per-bank ingestion config — one file per bank at ``config/banks/<bank>.yaml``.

Each bank declares how it ingests (``api`` | ``csv`` | ``pdf``); that source is
what a frontend uses to decide the action (sync vs import a file), while every
bank then follows the same balance-chain verify → uncategorized-inbox path.

The loader is backward compatible: when a bank has no per-bank file yet it is
synthesized from the legacy ``banks.yaml`` entry plus its statement profile, so
existing setups keep working. ``fin banks migrate`` writes the new files.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from finance.statements.profile import StatementProfile, generic_profile, load_profile

SOURCES = ("api", "csv", "pdf")


@dataclass
class BankConfig:
    bank: str                                   # the key, eg "investec"
    name: str
    currency: str = "ZAR"
    source: str = "csv"                         # api | csv | pdf
    provider: str | None = None                 # for source=api, eg "investec"
    password_env: str | None = None             # env var holding a PDF password
    statements_dir: str | None = None           # subfolder to watch for files
    api: dict = field(default_factory=dict)
    accounts: dict[str, dict] = field(default_factory=dict)
    profile: StatementProfile | None = None     # parsing profile for csv/pdf
    _ledger_account: str | None = None          # legacy top-level fallback

    def ledger_account(self, account: str = "checking") -> str:
        acct = self.accounts.get(account) or {}
        if acct.get("ledger_account"):
            return acct["ledger_account"]
        if self._ledger_account:
            return self._ledger_account
        return f"assets:bank:{self.bank}:{account}"

    def account_names(self) -> list[str]:
        return sorted(self.accounts) or ["checking"]

    def parse_profile(self, account: str = "checking") -> StatementProfile:
        """The profile to parse this bank's files with (never None)."""
        if self.profile is not None:
            return self.profile
        return load_profile(self.bank, account)

    def to_provider_dict(self, account: str = "checking") -> dict:
        """Legacy bank_config dict shape the providers still consume."""
        return {
            "name": self.name,
            "type": account,
            "default_currency": self.currency,
            "ledger_account": self.ledger_account(account),
            "api": self.api,
            "accounts": self.accounts,
            "provider": self.provider,
        }

    @classmethod
    def from_dict(cls, data: dict, *, bank: str) -> BankConfig:
        ingest = data.get("ingest", {}) or {}
        name = data.get("name", bank)
        currency = data.get("currency", "ZAR")
        source = ingest.get("source", "csv")
        if source not in SOURCES:
            raise ValueError(f"bank {bank!r}: ingest.source must be one of {SOURCES}, got {source!r}")

        profile_data = ingest.get("profile")
        if profile_data:
            profile = StatementProfile.from_dict(profile_data, name=profile_data.get("name", bank))
        elif source in ("csv", "pdf"):
            profile = generic_profile(bank)
        else:
            profile = None
        if profile is not None:
            profile.currency = currency

        return cls(
            bank=bank,
            name=name,
            currency=currency,
            source=source,
            provider=ingest.get("provider"),
            password_env=ingest.get("password_env"),
            statements_dir=ingest.get("statements_dir"),
            api=ingest.get("api", {}) or {},
            accounts=data.get("accounts", {}) or {},
            profile=profile,
            _ledger_account=data.get("ledger_account"),
        )

    def to_dict(self) -> dict:
        """Serialize back to the per-bank file shape (for migrate/write)."""
        ingest: dict = {"source": self.source}
        if self.provider:
            ingest["provider"] = self.provider
        if self.api:
            ingest["api"] = self.api
        if self.password_env:
            ingest["password_env"] = self.password_env
        if self.statements_dir:
            ingest["statements_dir"] = self.statements_dir
        if self.profile is not None and self.source in ("csv", "pdf"):
            ingest["profile"] = _profile_to_dict(self.profile)
        return {"name": self.name, "currency": self.currency, "ingest": ingest,
                "accounts": self.accounts or {}}


def _profile_to_dict(p: StatementProfile) -> dict:
    out: dict = {"format": p.format}
    if p.header_marker:
        out["header_marker"] = p.header_marker
    if p.columns:
        out["columns"] = p.columns
    if p.date_formats:
        out["date_formats"] = p.date_formats
    out["order"] = p.order
    if p.require_balance_chain:
        out["require_balance_chain"] = True
    if p.account_name_from_preamble:
        out["account_name_from_preamble"] = True
    if p.pdf:
        out["pdf"] = p.pdf
    if p.delimiter != ",":
        out["delimiter"] = p.delimiter
    return out


def _legacy_bank(bank: str) -> BankConfig:
    """Synthesize a BankConfig from the legacy banks.yaml + statement profile."""
    from finance.config import load_app_config

    config = load_app_config()
    entry = config.banks.get("banks", {}).get(bank, {}) or {}
    profile = load_profile(bank)
    # Infer the source: a provider/api entry means live API, else the profile format.
    if entry.get("provider") or entry.get("api"):
        source = "api"
    else:
        source = profile.format if profile.format in ("csv", "pdf") else "csv"
    return BankConfig(
        bank=bank,
        name=entry.get("name", bank.title()),
        currency=entry.get("default_currency", profile.currency),
        source=source,
        provider=entry.get("provider") or (bank if source == "api" else None),
        api=entry.get("api", {}) or {},
        accounts=entry.get("accounts", {}) or {},
        profile=None if source == "api" else profile,
        _ledger_account=entry.get("ledger_account"),
    )


def load_bank(bank: str) -> BankConfig:
    """Resolve a bank's config: per-bank file first, else legacy synthesis."""
    from finance.config import load_app_config

    path = load_app_config().paths.banks_dir / f"{bank}.yaml"
    if path.exists():
        data = yaml.safe_load(path.read_text()) or {}
        return BankConfig.from_dict(data, bank=bank)
    return _legacy_bank(bank)


def list_banks() -> list[str]:
    """Every configured bank: per-bank files unioned with legacy banks.yaml."""
    from finance.config import load_app_config

    config = load_app_config()
    banks: set[str] = set()
    banks_dir = config.paths.banks_dir
    if banks_dir.exists():
        banks |= {p.stem for p in banks_dir.glob("*.yaml")}
    banks |= set(config.banks.get("banks", {}))
    return sorted(banks)
