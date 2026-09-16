"""Analysis: recurring detection, cashflow, category trends."""

from __future__ import annotations

from decimal import Decimal

from finance.analysis.cashflow import monthly_cashflow
from finance.analysis.recurring import detect_recurring
from finance.analysis.trends import category_trends
from finance.models.transaction import TransactionRecord, TransactionSplit


def _rec(date, description, category, amount, *, splits=None):
    return TransactionRecord(
        id=f"{description}-{date}-{amount}", institution="investec", source_account="checking",
        ledger_account="assets:bank:investec:checking", date=date, description=description,
        amount=amount, currency="ZAR", category=category, category_source="manual",
        status="cleared", imported_at="2026-01-01T00:00:00Z", splits=splits or [],
    )


# ── recurring ────────────────────────────────────────────────────────────────

def test_detects_monthly_subscription():
    records = [
        _rec(f"2026-0{m}-05", "NETFLIX", "expenses:subscriptions", "-199.00") for m in range(1, 6)
    ]
    found = detect_recurring(records, as_of="2026-05-10")
    assert len(found) == 1
    r = found[0]
    assert r.cadence == "monthly"
    assert r.amount_stable and r.active
    assert r.typical_amount == Decimal("199.00")
    assert r.occurrences == 5


def test_irregular_merchant_not_flagged():
    records = [
        _rec("2026-01-05", "RANDOM SHOP", "expenses:other", "-50.00"),
        _rec("2026-01-19", "RANDOM SHOP", "expenses:other", "-90.00"),
        _rec("2026-04-02", "RANDOM SHOP", "expenses:other", "-12.00"),
    ]
    assert detect_recurring(records) == []


def test_lapsed_subscription_marked_inactive():
    records = [_rec(f"2026-0{m}-05", "OLDGYM", "expenses:membership:gym", "-500.00") for m in range(1, 4)]
    # as_of long after the last charge -> lapsed
    found = detect_recurring(records, as_of="2026-09-01")
    assert found and found[0].active is False


def test_min_occurrences_respected():
    records = [_rec(f"2026-0{m}-05", "TWICE", "expenses:other", "-10.00") for m in range(1, 3)]
    assert detect_recurring(records, min_occurrences=3) == []


# ── cashflow ─────────────────────────────────────────────────────────────────

def test_monthly_cashflow_with_split():
    records = [
        _rec("2026-01-25", "SALARY", "income:salary", "5000.00"),
        _rec("2026-01-10", "WOOLIES", "expenses:groceries", "-1000.00"),
        _rec("2026-01-15", "PUB", "split", "-300.00", splits=[
            TransactionSplit("expenses:lifestyle:drinks", "200.00"),
            TransactionSplit("expenses:lifestyle:eating-out", "100.00"),
        ]),
    ]
    (jan,) = monthly_cashflow(records)
    assert jan.income == Decimal("5000.00")
    assert jan.spend == Decimal("1300.00")     # 1000 + split 300
    assert jan.net == Decimal("3700.00")
    assert round(jan.savings_rate, 2) == 0.74


def test_cashflow_ignores_transfers():
    records = [
        _rec("2026-02-01", "MOVE", "assets:bank:investec:savings", "-1000.00"),  # transfer, not spend
        _rec("2026-02-02", "SHOP", "expenses:groceries", "-100.00"),
    ]
    (feb,) = monthly_cashflow(records)
    assert feb.spend == Decimal("100.00")
    assert feb.income == Decimal("0")
    assert feb.savings_rate is None            # no income


# ── trends ───────────────────────────────────────────────────────────────────

def test_category_trends_change_vs_average():
    records = [
        _rec("2026-01-10", "A", "expenses:food:groceries", "-100.00"),
        _rec("2026-02-10", "A", "expenses:food:dining", "-100.00"),      # rolls up to expenses:food
        _rec("2026-03-10", "A", "expenses:food:groceries", "-300.00"),
    ]
    trends, months = category_trends(records, months=3, depth=2)
    assert months == ["2026-01", "2026-02", "2026-03"]
    food = next(t for t in trends if t.category == "expenses:food")
    assert food.latest == Decimal("300.00")
    assert food.previous_avg == Decimal("100.00")
    assert food.change == Decimal("200.00")
    assert round(food.change_pct, 2) == 2.0


def test_trends_sorted_by_biggest_mover():
    records = [
        _rec("2026-01-10", "A", "expenses:small", "-10.00"),
        _rec("2026-02-10", "A", "expenses:small", "-12.00"),
        _rec("2026-01-10", "B", "expenses:big", "-100.00"),
        _rec("2026-02-10", "B", "expenses:big", "-900.00"),
    ]
    trends, _ = category_trends(records, months=2, depth=2)
    assert trends[0].category == "expenses:big"   # biggest absolute change first
