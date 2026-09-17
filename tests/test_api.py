"""API smoke tests via FastAPI's TestClient (no server)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from finance.api.app import create_app
from finance.models.transaction import TransactionRecord
from finance.services.init_data import initialize_data_dir
from finance.storage.jsonl_store import JsonlTransactionStore


def _rec(id_, description, category, amount="-50.00"):
    return TransactionRecord(
        id=id_, institution="investec", source_account="checking",
        ledger_account="assets:bank:investec:checking", date="2026-01-05", description=description,
        amount=amount, currency="ZAR", category=category, category_source="manual",
        status="cleared", imported_at="2026-01-05T00:00:00Z",
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    d = tmp_path / "data"
    initialize_data_dir(d)
    monkeypatch.setenv("FIN_DATA_DIR", str(d))
    monkeypatch.delenv("FIN_API_TOKEN", raising=False)
    JsonlTransactionStore(d / "transactions").write_file(
        d / "transactions" / "investec" / "2026.jsonl",
        [
            _rec("h1", "STARBUCKS CAPE TOWN ZA", "expenses:coffee"),
            _rec("h2", "STARBUCKS CAPE TOWN ZA 111111", "expenses:coffee"),
            _rec("h3", "Purchase at STARBUCKS Cape Town ZA 222222", "expenses:coffee"),
            _rec("u1", "STARBUCKS CAPE TOWN ZA 333333", "expenses:unknown"),
            _rec("u2", "Purchase at MYSTERY DELI Cape Town ZA 444444", "expenses:unknown"),
        ],
    )
    return TestClient(create_app())


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_status_counts(client):
    s = client.get("/status").json()
    assert s["uncategorized"] == 2
    assert s["needs_review"] == 0


def test_plan_recommends_from_history(client):
    plan = client.get("/categorize/plan", params={"bank": "investec", "scope": "uncat"}).json()
    assert len(plan) == 2
    starbucks = next(p for p in plan if p["record"]["id"] == "u1")
    assert starbucks["classification"]["recommended"] == "expenses:coffee"
    assert starbucks["classification"]["auto"] is True

    # the merchant_key lets the TUI peek at the merchant's history
    key = starbucks["classification"]["merchant_key"]
    assert key
    detail = client.get(f"/merchants/{key}").json()
    assert detail["merchant"] == "Starbucks"
    assert any(b["category"] == "expenses:coffee" for b in detail["breakdown"])


def test_auto_then_review_then_confirm(client):
    result = client.post("/categorize/auto", json={"bank": "investec"}).json()
    assert result["auto_applied"] == 1
    assert result["needs_review"] == 1

    review = client.get("/categorize/plan", params={"bank": "investec", "scope": "review"}).json()
    assert [p["record"]["id"] for p in review] == ["u1"]

    client.post("/categorize/confirm", json={"bank": "investec", "ids": ["u1"]})
    review2 = client.get("/categorize/plan", params={"bank": "investec", "scope": "review"}).json()
    assert review2 == []


def test_apply_and_reject(client):
    client.post("/categorize/apply", json={"bank": "investec", "id": "u2", "category": "expenses:other"})
    txns = client.get("/transactions", params={"bank": "investec"}).json()
    assert {t["id"]: t for t in txns}["u2"]["category"] == "expenses:other"

    client.post("/categorize/reject", json={"bank": "investec", "id": "u2"})
    txns = client.get("/transactions", params={"bank": "investec"}).json()
    assert {t["id"]: t for t in txns}["u2"]["category"] == "expenses:unknown"


def test_apply_returns_before_after_and_restore_undoes(client):
    resp = client.post("/categorize/apply",
                       json={"bank": "investec", "id": "u2", "category": "expenses:other"}).json()
    assert resp["before"]["category"] == "expenses:unknown"
    assert resp["after"]["category"] == "expenses:other"

    # undo: restore the "before" snapshot
    assert client.post("/categorize/restore",
                       json={"bank": "investec", "record": resp["before"]}).json()["ok"] is True
    u2 = {t["id"]: t for t in client.get("/transactions", params={"bank": "investec"}).json()}["u2"]
    assert u2["category"] == "expenses:unknown"

    # redo: restore the "after" snapshot
    assert client.post("/categorize/restore",
                       json={"bank": "investec", "record": resp["after"]}).json()["ok"] is True
    u2 = {t["id"]: t for t in client.get("/transactions", params={"bank": "investec"}).json()}["u2"]
    assert u2["category"] == "expenses:other"


def test_apply_splits(client):
    ok = client.post("/categorize/apply", json={
        "bank": "investec", "id": "u2",
        "splits": [{"account": "expenses:a", "amount": "20.00"}, {"account": "expenses:b", "amount": "30.00"}],
    }).json()
    assert ok["ok"] is True
    u2 = {t["id"]: t for t in client.get("/transactions", params={"bank": "investec"}).json()}["u2"]
    assert u2["category"] == "split"


def test_split_that_does_not_sum_is_400(client):
    resp = client.post("/categorize/apply", json={
        "bank": "investec", "id": "u2",
        "splits": [{"account": "expenses:a", "amount": "20.00"}],
    })
    assert resp.status_code == 400


def test_banks_endpoint_reports_source(client):
    banks = {b["bank"]: b for b in client.get("/banks").json()}
    assert "investec" in banks
    assert banks["investec"]["source"] == "api"   # seeded legacy investec has an api block
    assert "checking" in banks["investec"]["accounts"]


def test_add_category_and_taxonomy(client):
    assert client.get("/taxonomy").json()["categories"] == []
    client.post("/categories", json={"category": "expenses:new"})
    assert "expenses:new" in client.get("/taxonomy").json()["categories"]


def test_add_rule(client):
    name = client.post("/rules", json={"category": "expenses:lifestyle:bars", "merchant": "punk bar"}).json()["name"]
    assert name


def test_merchants(client):
    m = client.get("/merchants").json()
    assert any(row["key"] == "starbucks" and row["top_category"] == "expenses:coffee" for row in m)


def test_auth_required_when_token_set(tmp_path, monkeypatch):
    d = tmp_path / "data"
    initialize_data_dir(d)
    monkeypatch.setenv("FIN_DATA_DIR", str(d))
    monkeypatch.setenv("FIN_API_TOKEN", "secret")
    c = TestClient(create_app())
    assert c.get("/health").status_code == 200                      # health is open
    assert c.get("/status").status_code == 401                      # guarded, no token
    assert c.get("/status", headers={"Authorization": "Bearer secret"}).status_code == 200
