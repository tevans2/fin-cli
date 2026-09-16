"""Extended rule matching and rule creation/round-trip."""

from __future__ import annotations

import pytest

from finance.models.rules import Rule, RuleMatch
from finance.models.transaction import TransactionRecord
from finance.services.init_data import initialize_data_dir
from finance.services.rules import create_rule, list_rules
from finance.storage.rules_store import RulesStore, match_rule


def _rec(description="YOCO *PUNK BAR STELLENBOSCH ZA", *, amount="-40.00", account="checking", institution="investec"):
    return TransactionRecord(
        id="t", institution=institution, source_account=account,
        ledger_account=f"assets:bank:{institution}:{account}", date="2026-01-01", description=description,
        amount=amount, currency="ZAR", category="expenses:unknown", category_source="default:unknown",
        status="cleared", imported_at="2026-01-01T00:00:00Z",
    )


def test_match_on_merchant_key():
    rule = Rule(name="pb", category="c", match=RuleMatch(merchant="punk bar"))
    assert match_rule(rule, _rec())                                   # normalizes to "punk bar"
    assert not match_rule(rule, _rec(description="SOMEWHERE ELSE ZA"))


def test_match_on_direction():
    out_rule = Rule(name="o", category="c", match=RuleMatch(direction="out"))
    in_rule = Rule(name="i", category="c", match=RuleMatch(direction="in"))
    assert match_rule(out_rule, _rec(amount="-40.00"))
    assert not match_rule(out_rule, _rec(amount="40.00"))
    assert match_rule(in_rule, _rec(amount="40.00"))


def test_match_on_account_and_institution():
    rule = Rule(name="a", category="c", match=RuleMatch(account="savings", institution="tyme"))
    assert match_rule(rule, _rec(account="savings", institution="tyme"))
    assert not match_rule(rule, _rec(account="checking", institution="tyme"))


def test_combined_conditions_are_anded():
    rule = Rule(name="x", category="c", match=RuleMatch(merchant="punk bar", direction="out", amount_gt="-100"))
    assert match_rule(rule, _rec(amount="-40.00"))     # merchant + out + -40 > -100
    assert not match_rule(rule, _rec(amount="-150.00"))  # -150 not > -100


def test_rule_to_dict_round_trip():
    rule = Rule(name="r", category="expenses:x", priority=50, match=RuleMatch(merchant="punk bar", direction="out"))
    restored = Rule.from_dict(rule.to_dict())
    assert restored.name == "r"
    assert restored.match.merchant == "punk bar"
    assert restored.match.direction == "out"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    initialize_data_dir(d)
    monkeypatch.setenv("FIN_DATA_DIR", str(d))
    return d


def test_create_rule_appends_and_is_unique(data_dir):
    n1 = create_rule("expenses:lifestyle:drinks", merchant="Punk Bar")
    n2 = create_rule("expenses:lifestyle:drinks", merchant="Punk Bar")   # same base name
    assert n1 != n2                                                      # de-duplicated
    names = {r["name"] for r in list_rules()}
    assert n1 in names and n2 in names


def test_create_rule_requires_a_condition(data_dir):
    with pytest.raises(ValueError):
        create_rule("expenses:x")


def test_created_rule_matches(data_dir):
    create_rule("expenses:lifestyle:drinks", merchant="Punk Bar")
    from finance.config import load_app_config
    rules = RulesStore(load_app_config().paths.rules_config).load()
    matching = [r for r in rules if match_rule(r, _rec())]
    assert any(r.category == "expenses:lifestyle:drinks" for r in matching)
