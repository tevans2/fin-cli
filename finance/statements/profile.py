from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from finance.statements.model import StatementFormatError

# Canonical fields a profile can map source columns onto.
FIELDS = ("date", "action_date", "description", "amount", "debit", "credit", "balance", "reference")

# Number cleaning is universal: strip currency symbol, thousands separators and
# spaces, and read (123) as -123.
DEFAULT_DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"]


@dataclass
class StatementProfile:
    name: str
    id_prefix: str
    format: str = "csv"                       # "csv" | "pdf"
    delimiter: str = ","
    encoding: str = "utf-8-sig"
    currency: str = "ZAR"
    # None => the header is the first row. Otherwise, the first row that contains
    # all of these column names (case/space-insensitive) is the header, and lines
    # above it are treated as a preamble.
    header_marker: list[str] | None = None
    columns: dict[str, list[str]] = field(default_factory=dict)
    date_formats: list[str] = field(default_factory=lambda: list(DEFAULT_DATE_FORMATS))
    order: str = "chronological"              # "chronological" | "newest_first"
    require_balance_chain: bool = False
    account_name_from_preamble: bool = False
    pdf: dict | None = None                   # pdf-specific settings (line_regex, etc.)

    @classmethod
    def from_dict(cls, data: dict, *, name: str) -> StatementProfile:
        raw_columns = data.get("columns", {}) or {}
        columns = {
            field_name: ([aliases] if isinstance(aliases, str) else list(aliases))
            for field_name, aliases in raw_columns.items()
        }
        unknown = set(columns) - set(FIELDS)
        if unknown:
            raise StatementFormatError(f"Profile {name!r} has unknown column fields: {', '.join(sorted(unknown))}")
        return cls(
            name=name,
            id_prefix=data.get("id_prefix", name),
            format=data.get("format", "csv"),
            delimiter=data.get("delimiter", ","),
            encoding=data.get("encoding", "utf-8-sig"),
            currency=data.get("currency", "ZAR"),
            header_marker=data.get("header_marker"),
            columns=columns,
            date_formats=data.get("date_formats") or list(DEFAULT_DATE_FORMATS),
            order=data.get("order", "chronological"),
            require_balance_chain=bool(data.get("require_balance_chain", False)),
            account_name_from_preamble=bool(data.get("account_name_from_preamble", False)),
            pdf=data.get("pdf"),
        )


# ── built-in profiles (so investec/tyme work with zero config) ────────────────

_GENERIC_COLUMNS = {
    "date": ["date", "transaction date", "posting date", "value date"],
    "description": ["description", "details", "transaction", "narration", "merchant"],
    "amount": ["amount", "transaction amount", "signed amount"],
    "debit": ["debit", "withdrawal", "money out"],
    "credit": ["credit", "deposit", "money in"],
    "balance": ["balance", "running balance", "available balance"],
    "reference": ["reference", "ref", "transaction id", "id"],
}


def generic_profile(bank: str) -> StatementProfile:
    """Alias-based profile for a bank with no explicit profile yet."""
    return StatementProfile(
        name=bank,
        id_prefix=bank,
        columns=dict(_GENERIC_COLUMNS),
        date_formats=list(DEFAULT_DATE_FORMATS),
        order="chronological",
        require_balance_chain=False,
    )


def _investec_profile() -> StatementProfile:
    return StatementProfile(
        name="investec",
        id_prefix="investec-csv",
        header_marker=["Transaction Date", "Posting Date", "Description", "Debits", "Credits", "Balance"],
        columns={
            "date": ["Posting Date"],
            "action_date": ["Transaction Date"],
            "description": ["Description"],
            "debit": ["Debits"],
            "credit": ["Credits"],
            "balance": ["Balance"],
        },
        date_formats=["%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y"],
        order="newest_first",
        require_balance_chain=True,
        account_name_from_preamble=True,
    )


def _tyme_profile() -> StatementProfile:
    return StatementProfile(
        name="tyme",
        id_prefix="tyme",
        columns=dict(_GENERIC_COLUMNS),
        date_formats=list(DEFAULT_DATE_FORMATS),
        order="chronological",
        require_balance_chain=False,
    )


BUILTIN_PROFILES = {
    "investec": _investec_profile,
    "tyme": _tyme_profile,
}


def load_profile(bank: str, account: str = "checking", *, config_dir: Path | None = None) -> StatementProfile:
    """Resolve the profile for a bank/account.

    Order: ``config/statements/<bank>-<account>.yaml`` → ``<bank>.yaml`` →
    built-in (investec/tyme) → a generic alias-based profile.
    """
    if config_dir is None:
        from finance.config import load_app_config

        config_dir = load_app_config().paths.config_dir
    statements_dir = config_dir / "statements"
    for candidate in (statements_dir / f"{bank}-{account}.yaml", statements_dir / f"{bank}.yaml"):
        if candidate.exists():
            data = yaml.safe_load(candidate.read_text()) or {}
            return StatementProfile.from_dict(data, name=data.get("name", bank))
    if bank in BUILTIN_PROFILES:
        return BUILTIN_PROFILES[bank]()
    return generic_profile(bank)
