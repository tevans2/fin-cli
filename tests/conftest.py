"""Shared test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_app_config(tmp_path_factory, monkeypatch):
    """Point FIN_CONFIG_DIR at a fresh empty dir so tests never touch ~/.config/fin."""
    monkeypatch.setenv("FIN_CONFIG_DIR", str(tmp_path_factory.mktemp("fin-config")))
