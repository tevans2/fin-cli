from __future__ import annotations

import csv
import io
import subprocess
from decimal import Decimal

import pandas as pd
import requests
import streamlit as st

from finance.config import load_app_config
from finance.storage.investment_store import InvestmentStore
from finance.storage.jsonl_store import JsonlTransactionStore


@st.cache_data(ttl=60)
def load_transactions() -> pd.DataFrame:
    config = load_app_config()
    store = JsonlTransactionStore(config.paths.transactions_dir)

    rows = []
    txn_dir = config.paths.transactions_dir
    if not txn_dir.exists():
        return pd.DataFrame()

    for bank_dir in sorted(txn_dir.iterdir()):
        if not bank_dir.is_dir() or bank_dir.name.startswith("."):
            continue
        for path in sorted(bank_dir.glob("*.jsonl")):
            for r in store.read_file(path):
                rows.append({
                    "id": r.id,
                    "date": r.date,
                    "bank": r.institution,
                    "account": r.source_account,
                    "description": r.description,
                    "display_name": r.alias or r.description,
                    "amount": float(r.amount),
                    "currency": r.currency,
                    "category": r.category,
                    "category_source": r.category_source,
                    "status": r.status,
                })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M")
    df["top_category"] = df["category"].apply(
        lambda c: ":".join(c.split(":")[:2]) if ":" in c else c
    )
    return df


def _parse_zar(s: str) -> float | None:
    parts = s.strip().split()
    if len(parts) == 2 and parts[1] == "ZAR":
        try:
            return float(parts[0].replace(",", ""))
        except ValueError:
            pass
    return None


@st.cache_data(ttl=3600)
def get_usd_zar_rate() -> tuple[float, str] | tuple[None, None]:
    """Fetch live USD/ZAR rate. Returns (rate, timestamp) or (None, None) on failure."""
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        r.raise_for_status()
        data = r.json()
        rate = data["rates"]["ZAR"]
        updated = data.get("time_last_update_utc", "")
        return float(rate), updated
    except Exception:
        return None, None


@st.cache_data(ttl=300)
def load_investments() -> pd.DataFrame:
    """Load all investment valuations into a flat DataFrame."""
    config = load_app_config()
    store = InvestmentStore(config.paths.investments_dir)

    rows = []
    for name in store.all_names():
        valuations = store.read(name)
        if not valuations:
            continue
        baseline = next((v for v in valuations if v.is_baseline), valuations[0])
        baseline_value = Decimal(baseline.value)
        for v in valuations:
            rows.append({
                "name": v.name,
                "account": v.account,
                "date": v.date,
                "value": float(v.value),
                "currency": v.currency,
                "is_baseline": v.is_baseline,
                "notes": v.notes,
                "baseline_value": float(baseline_value),
            })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["gain"] = df["value"] - df["baseline_value"]
    df["gain_pct"] = (df["gain"] / df["baseline_value"] * 100).round(2)

    rate, _ = get_usd_zar_rate()
    if rate:
        df["value_zar"] = df.apply(
            lambda r: r["value"] * rate if r["currency"] == "USD" else r["value"], axis=1
        )
        df["baseline_zar"] = df.apply(
            lambda r: r["baseline_value"] * rate if r["currency"] == "USD" else r["baseline_value"], axis=1
        )
    else:
        df["value_zar"] = df.apply(
            lambda r: None if r["currency"] == "USD" else r["value"], axis=1
        )
        df["baseline_zar"] = df.apply(
            lambda r: None if r["currency"] == "USD" else r["baseline_value"], axis=1
        )

    return df


@st.cache_data(ttl=300)
def get_balances() -> pd.DataFrame:
    config = load_app_config()
    cmd = [
        "hledger", "--no-conf",
        "-f", str(config.paths.main_journal),
        "bal", "assets", "liabilities",
        "--flat", "--no-total", "-O", "csv",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return pd.DataFrame()

    rows = []
    for row in csv.DictReader(io.StringIO(result.stdout)):
        account = row["account"]
        balance = _parse_zar(row["balance"])
        if balance is None:
            continue
        if "investments" in account:
            group = "investments"
        elif account.startswith("liabilities"):
            group = "liabilities"
        else:
            group = "liquid"
        rows.append({"account": account, "balance": balance, "group": group})

    return pd.DataFrame(rows) if rows else pd.DataFrame()
