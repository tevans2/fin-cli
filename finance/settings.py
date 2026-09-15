"""User/CLI settings, stored in a config directory outside the data repo.

The data repo (``FIN_DATA_DIR``) holds per-account data config — banks, rules,
aliases, statement profiles — versioned and encrypted with the data. This module
holds *app-level* settings that belong to the machine, not the data: where the
data repo is, which OpenAI model to use, and so on.

Config directory resolution: ``$FIN_CONFIG_DIR`` → ``$XDG_CONFIG_HOME/fin`` →
``~/.config/fin``. It contains ``config.yaml`` (settings) and optionally ``.env``
(secrets like OPENAI_API_KEY, <BANK>_DOC_CODE).

Every setting can be overridden by an environment variable, which always wins, so
existing workflows (``export FIN_DATA_DIR=...``) keep working.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# setting key -> environment variable that overrides it
ENV_OVERRIDES: dict[str, str] = {
    "data_dir": "FIN_DATA_DIR",
    "openai_model": "OPENAI_MODEL",
    "ai_attempts": "FIN_AI_ATTEMPTS",
}

# setting key -> default when neither env nor config.yaml provides one
DEFAULTS: dict[str, Any] = {
    "openai_model": "gpt-4o-mini",
    "ai_attempts": 3,
}

# keys coerced to int when set/read
_INT_KEYS = {"ai_attempts"}

KNOWN_KEYS = sorted(set(ENV_OVERRIDES) | set(DEFAULTS) | {"data_dir"})


def config_dir() -> Path:
    override = os.getenv("FIN_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.getenv("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "fin"


def config_file() -> Path:
    return config_dir() / "config.yaml"


def env_file() -> Path:
    return config_dir() / ".env"


def normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _coerce(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in _INT_KEYS:
        return int(value)
    return value


def load() -> dict:
    path = config_file()
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def source_of(key: str) -> str:
    """Where the effective value comes from: 'env', 'config', 'default', or 'unset'."""
    env = ENV_OVERRIDES.get(key)
    if env and os.getenv(env) not in (None, ""):
        return "env"
    if key in load():
        return "config"
    if key in DEFAULTS:
        return "default"
    return "unset"


def get(key: str, default: Any = None) -> Any:
    key = normalize_key(key)
    env = ENV_OVERRIDES.get(key)
    if env:
        env_value = os.getenv(env)
        if env_value not in (None, ""):
            return _coerce(key, env_value)
    data = load()
    if data.get(key) not in (None, ""):
        return _coerce(key, data[key])
    if default is not None:
        return _coerce(key, default)
    return DEFAULTS.get(key)


def set_value(key: str, value: Any) -> Path:
    key = normalize_key(key)
    if key not in KNOWN_KEYS:
        raise KeyError(f"Unknown setting {key!r}. Known keys: {', '.join(KNOWN_KEYS)}")
    data = load()
    if value in (None, ""):
        data.pop(key, None)
    else:
        data[key] = _coerce(key, value)
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=True))
    return path


def resolved() -> dict[str, dict[str, Any]]:
    """All known settings with their effective value and source."""
    return {key: {"value": get(key), "source": source_of(key)} for key in KNOWN_KEYS}
