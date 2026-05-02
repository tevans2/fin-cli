from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from finance.config import load_app_config
from finance.models.investment import InvestmentValuation, utc_now_iso
from finance.storage.investment_store import InvestmentStore


def _account_for(name: str, account_override: str | None) -> str:
    return account_override or f"assets:investments:{name}"


def set_valuation(
    name: str,
    value: str,
    *,
    date: str,
    currency: str = "ZAR",
    notes: str | None = None,
    account_override: str | None = None,
    is_baseline: bool = False,
) -> dict:
    config = load_app_config()
    store = InvestmentStore(config.paths.investments_dir)
    account = _account_for(name, account_override)

    valuation = InvestmentValuation(
        name=name,
        account=account,
        date=date,
        value=f"{Decimal(value):.2f}",
        currency=currency,
        notes=notes,
        recorded_at=utc_now_iso(),
        is_baseline=is_baseline,
    )
    valuation.validate()
    store.append(valuation)

    journal_result = build_investment_journal()
    return {
        "name": name,
        "account": account,
        "date": date,
        "value": valuation.value,
        "journal_output": journal_result["output"],
    }


def build_investment_journal() -> dict:
    config = load_app_config()
    store = InvestmentStore(config.paths.investments_dir)
    names = store.all_names()

    lines: list[str] = ["; Generated investment valuations — do not edit manually\n"]

    for name in names:
        valuations = store.read(name)
        if not valuations:
            continue
        prev_value = Decimal("0")
        for v in valuations:
            current = Decimal(v.value)
            delta = current - prev_value
            prev_value = current
            if v.is_baseline or delta == 0:
                continue
            note = f"  ; {v.notes}" if v.notes else ""
            lines.append(f"\n{v.date} * {name} valuation{note}")
            lines.append(f"    {v.account}    {delta:.2f} {v.currency}")
            lines.append(f"    income:unrealised-gains    {-delta:.2f} {v.currency}")

    output = config.paths.generated_investment_journal
    output.parent.mkdir(parents=True, exist_ok=True)

    _ensure_included(config.paths.main_journal, "generated/investments.journal")

    output.write_text("\n".join(lines) + "\n")
    return {"output": str(output), "accounts": names}


def list_investments() -> list[dict]:
    config = load_app_config()
    store = InvestmentStore(config.paths.investments_dir)
    results = []
    for name in store.all_names():
        valuations = store.read(name)
        if not valuations:
            continue
        latest = valuations[-1]
        opening = Decimal("0")
        delta_since_open = Decimal(latest.value) - opening
        results.append({
            "name": name,
            "account": latest.account,
            "value": latest.value,
            "currency": latest.currency,
            "date": latest.date,
            "delta_since_opening": f"{delta_since_open:.2f}",
        })
    return results


def get_history(name: str) -> list[dict]:
    config = load_app_config()
    store = InvestmentStore(config.paths.investments_dir)
    valuations = store.read(name)
    if not valuations:
        return []
    prev = Decimal("0")
    rows = []
    for v in valuations:
        current = Decimal(v.value)
        rows.append({
            "date": v.date,
            "value": v.value,
            "delta": f"{current - prev:.2f}",
            "currency": v.currency,
            "notes": v.notes,
        })
        prev = current
    return rows


def _ensure_included(main_journal: Path, include_line: str) -> None:
    if not main_journal.exists():
        return
    content = main_journal.read_text()
    entry = f"include {include_line}"
    if entry not in content:
        main_journal.write_text(content.rstrip() + f"\n{entry}\n")
