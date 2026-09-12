"""Data shaping for the web viewing pages.

Reads through the service layer + the shared hledger helper and returns plain
dicts/lists for the templates. No pandas, no framework state — kept light on
purpose.
"""

from __future__ import annotations

from decimal import Decimal

from finance.config import load_app_config
from finance.models.transaction import TransactionRecord
from finance.services import hledger
from finance.services.transactions import load_all_transactions
from finance.storage.investment_store import InvestmentStore


def _parse_amount(raw: str) -> float | None:
    """Parse an hledger CSV balance cell like '1,234.56 ZAR'."""
    parts = raw.strip().split()
    if not parts:
        return None
    try:
        return float(parts[0].replace(",", ""))
    except ValueError:
        return None


def _group_for(account: str) -> str:
    if "investments" in account:
        return "investments"
    if account.startswith("liabilities"):
        return "liabilities"
    return "liquid"


def net_worth() -> dict:
    """Balances of assets + liabilities, grouped, with a net-worth total."""
    rows = hledger.read_csv(["balance", "assets", "liabilities", "--flat", "--no-total"])
    groups: dict[str, list[dict]] = {"liquid": [], "investments": [], "liabilities": []}
    for row in rows:
        account = row.get("account", "")
        balance = _parse_amount(row.get("balance", ""))
        if not account or balance is None:
            continue
        groups[_group_for(account)].append({"account": account, "balance": balance})

    totals = {g: sum(r["balance"] for r in items) for g, items in groups.items()}
    return {
        "groups": groups,
        "totals": totals,
        "net_worth": sum(totals.values()),
    }


def investments() -> list[dict]:
    """Latest value + gain vs baseline for each investment."""
    config = load_app_config()
    store = InvestmentStore(config.paths.investments_dir)
    out: list[dict] = []
    for name in store.all_names():
        valuations = store.read(name)
        if not valuations:
            continue
        baseline = next((v for v in valuations if v.is_baseline), valuations[0])
        latest = valuations[-1]
        base_val = Decimal(baseline.value)
        latest_val = Decimal(latest.value)
        gain = latest_val - base_val
        gain_pct = float(gain / base_val * 100) if base_val else 0.0
        out.append({
            "name": name,
            "account": latest.account,
            "currency": latest.currency,
            "value": float(latest_val),
            "baseline": float(base_val),
            "gain": float(gain),
            "gain_pct": round(gain_pct, 1),
            "date": latest.date,
        })
    return out


def _distinct(records: list[TransactionRecord], key) -> list[str]:
    return sorted({key(r) for r in records if key(r)})


def _row(r: TransactionRecord) -> dict:
    """Shape a TransactionRecord into a flat dict for table rendering."""
    return {
        "id": r.id,
        "date": r.date,
        "bank": r.institution,
        "account": r.source_account,
        "name": r.alias or r.description,
        "amount": float(r.amount),
        "currency": r.currency,
        "category": r.category,
        "source": r.category_source,
    }


def transactions_view(
    bank: str = "",
    account: str = "",
    category: str = "",
    month: str = "",
    query: str = "",
    begin: str = "",
    end: str = "",
    match: str = "",
    limit: int = 500,
) -> dict:
    """Filtered transactions plus the distinct values for the filter dropdowns.

    `begin`/`end` are inclusive YYYY-MM-DD bounds (lexical compare is safe for
    that format). `match` is a broad substring test across description, alias,
    category, account and bank — used by the reports panel's free-text box.
    """
    records = load_all_transactions()

    banks = _distinct(records, lambda r: r.institution)
    accounts = _distinct(records, lambda r: r.source_account)
    categories = _distinct(records, lambda r: r.category)
    months = sorted({r.date[:7] for r in records if r.date}, reverse=True)

    q = query.strip().lower()
    m = match.strip().lower()
    filtered = [
        r for r in records
        if (not bank or r.institution == bank)
        and (not account or r.source_account == account)
        and (not category or r.category == category)
        and (not month or r.date.startswith(month))
        and (not begin or r.date >= begin)
        and (not end or r.date <= end)
        and (not q or q in r.description.lower() or (r.alias and q in r.alias.lower()))
        and (not m or m in r.description.lower() or m in r.category.lower()
             or m in r.source_account.lower() or m in r.institution.lower()
             or (r.alias and m in r.alias.lower()))
    ]
    filtered.reverse()  # newest first

    total_in = sum(float(r.amount) for r in filtered if float(r.amount) > 0)
    total_out = sum(float(r.amount) for r in filtered if float(r.amount) < 0)

    rows = [_row(r) for r in filtered[:limit]]

    return {
        "rows": rows,
        "count": len(filtered),
        "shown": len(rows),
        "limit": limit,
        "total_in": total_in,
        "total_out": total_out,
        "options": {"banks": banks, "accounts": accounts, "categories": categories, "months": months},
        "selected": {
            "bank": bank, "account": account, "category": category,
            "month": month, "query": query, "begin": begin, "end": end, "match": match,
        },
    }


def find_txn_row(txn_id: str) -> dict | None:
    """Locate a single transaction by id and shape it for a row swap."""
    for r in load_all_transactions():
        if r.id == txn_id:
            return _row(r)
    return None
