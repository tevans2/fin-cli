"""Per-bank ingestion config: per-bank files, legacy fallback, round-trip."""

from __future__ import annotations

import pytest
import yaml

from finance.banks import BankConfig, list_banks, load_bank
from finance.services.init_data import initialize_data_dir


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    initialize_data_dir(d)  # seeds legacy banks.yaml with investec + tyme
    monkeypatch.setenv("FIN_DATA_DIR", str(d))
    return d


def _write_bank(data_dir, bank, doc):
    banks_dir = data_dir / "config" / "banks"
    banks_dir.mkdir(parents=True, exist_ok=True)
    (banks_dir / f"{bank}.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))


def test_per_bank_pdf_file_wins(data_dir):
    _write_bank(data_dir, "tyme", {
        "name": "TymeBank",
        "currency": "ZAR",
        "ingest": {
            "source": "pdf",
            "password_env": "TYME_DOC_CODE",
            "profile": {"format": "pdf", "require_balance_chain": True,
                        "columns": {"date": ["date"], "amount": ["amount"], "balance": ["balance"]}},
        },
        "accounts": {"checking": {"ledger_account": "assets:bank:tyme:checking"}},
    })
    b = load_bank("tyme")
    assert b.source == "pdf"
    assert b.password_env == "TYME_DOC_CODE"
    assert b.ledger_account("checking") == "assets:bank:tyme:checking"
    assert b.parse_profile().format == "pdf"
    assert b.parse_profile().require_balance_chain is True
    assert b.parse_profile().currency == "ZAR"


def test_api_bank_from_file(data_dir):
    _write_bank(data_dir, "investec", {
        "name": "Investec",
        "currency": "ZAR",
        "ingest": {"source": "api", "provider": "investec", "api": {"timeout_seconds": 30}},
        "accounts": {"checking": {"ledger_account": "assets:bank:investec:checking"}},
    })
    b = load_bank("investec")
    assert b.source == "api"
    assert b.provider == "investec"
    assert b.to_provider_dict()["api"]["timeout_seconds"] == 30


def test_legacy_fallback_infers_api_for_investec(data_dir):
    # no per-bank file: synthesized from seeded banks.yaml (investec has an api block)
    b = load_bank("investec")
    assert b.source == "api"
    assert b.name == "Investec"
    assert b.ledger_account("checking") == "assets:bank:investec:checking"


def test_bad_source_rejected(data_dir):
    _write_bank(data_dir, "weird", {"name": "Weird", "ingest": {"source": "carrier-pigeon"}})
    with pytest.raises(ValueError):
        load_bank("weird")


def test_list_banks_unions_files_and_legacy(data_dir):
    _write_bank(data_dir, "fnb", {"name": "FNB", "ingest": {"source": "csv"}})
    banks = list_banks()
    assert {"investec", "tyme", "fnb"} <= set(banks)


def test_round_trip_to_dict(data_dir):
    doc = {
        "name": "FNB", "currency": "ZAR",
        "ingest": {"source": "csv",
                   "profile": {"format": "csv", "header_marker": ["Date", "Amount"],
                               "columns": {"date": ["Date"], "amount": ["Amount"]}}},
        "accounts": {"checking": {"ledger_account": "assets:bank:fnb:checking"}},
    }
    b = BankConfig.from_dict(doc, bank="fnb")
    again = BankConfig.from_dict(b.to_dict(), bank="fnb")
    assert again.source == "csv"
    assert again.parse_profile().header_marker == ["Date", "Amount"]
    assert again.ledger_account("checking") == "assets:bank:fnb:checking"
