"""App settings: config-dir resolution, precedence, and set/get."""

from __future__ import annotations

from pathlib import Path

import pytest

from finance import settings


def test_config_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("FIN_CONFIG_DIR", str(tmp_path / "c"))
    assert settings.config_dir() == tmp_path / "c"
    assert settings.config_file() == tmp_path / "c" / "config.yaml"
    assert settings.env_file() == tmp_path / "c" / ".env"


def test_config_dir_xdg_then_home(monkeypatch, tmp_path):
    monkeypatch.delenv("FIN_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert settings.config_dir() == tmp_path / "xdg" / "fin"
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert settings.config_dir() == Path.home() / ".config" / "fin"


def test_set_and_get_roundtrip():
    settings.set_value("data-dir", "/tmp/data")   # dashed key normalized
    assert settings.get("data_dir") == "/tmp/data"
    assert settings.source_of("data_dir") == "config"


def test_env_overrides_config(monkeypatch):
    settings.set_value("data_dir", "/from/config")
    monkeypatch.setenv("FIN_DATA_DIR", "/from/env")
    assert settings.get("data_dir") == "/from/env"
    assert settings.source_of("data_dir") == "env"


def test_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("FIN_AI_ATTEMPTS", raising=False)
    assert settings.get("openai_model") == "gpt-4o-mini"
    assert settings.get("ai_attempts") == 3
    assert isinstance(settings.get("ai_attempts"), int)


def test_int_coercion():
    settings.set_value("ai_attempts", "5")
    assert settings.get("ai_attempts") == 5


def test_unknown_key_rejected():
    with pytest.raises(KeyError):
        settings.set_value("nonsense", "x")


def test_unset_removes(monkeypatch):
    monkeypatch.delenv("FIN_DATA_DIR", raising=False)
    settings.set_value("data_dir", "/x")
    settings.set_value("data_dir", None)
    assert settings.get("data_dir") is None
    assert settings.source_of("data_dir") == "unset"


def test_resolve_data_dir_uses_settings(monkeypatch):
    from finance.paths import DataDirError, resolve_data_dir

    monkeypatch.delenv("FIN_DATA_DIR", raising=False)
    settings.set_value("data_dir", "/tmp/mydata")
    assert resolve_data_dir() == Path("/tmp/mydata").resolve()

    settings.set_value("data_dir", None)
    with pytest.raises(DataDirError):
        resolve_data_dir()
