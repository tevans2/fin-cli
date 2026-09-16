"""LLM category fallback — grounding and error handling (no real API calls)."""

from __future__ import annotations

import pytest

from finance.classify.llm import LLMError, suggest_category, validate_choice

CATEGORIES = ["expenses:groceries", "expenses:lifestyle:drinks", "income:salary"]


def test_validate_choice_only_accepts_known_categories():
    assert validate_choice("expenses:groceries", CATEGORIES) == "expenses:groceries"
    assert validate_choice("expenses:made-up", CATEGORIES) is None
    assert validate_choice(None, CATEGORIES) is None


def test_empty_taxonomy_raises():
    with pytest.raises(LLMError):
        suggest_category("Foo", "-10.00", "ZAR", [])


def test_missing_key_raises(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FIN_DATA_DIR", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMError):
        suggest_category("Foo", "-10.00", "ZAR", CATEGORIES)


class _FakeResp:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


def _fake_client(content):
    class _Completions:
        def create(self, **kwargs):
            return _FakeResp(content)

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    return lambda *a, **k: _Client()


def test_suggest_returns_grounded_category(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("openai.OpenAI", _fake_client('{"category": "expenses:lifestyle:drinks"}'))
    assert suggest_category("SOME BAR", "-50.00", "ZAR", CATEGORIES) == "expenses:lifestyle:drinks"


def test_suggest_rejects_invented_category(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("openai.OpenAI", _fake_client('{"category": "expenses:not-in-taxonomy"}'))
    assert suggest_category("MYSTERY", "-50.00", "ZAR", CATEGORIES) is None
