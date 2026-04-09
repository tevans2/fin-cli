from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import yaml

from .paths import DataPaths, get_data_paths


@dataclass(frozen=True)
class AppConfig:
    paths: DataPaths
    banks: dict
    rules: dict
    aliases: dict


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _load_yaml_default(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    with open(path) as f:
        return yaml.safe_load(f) or default


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        os.environ.setdefault(key, value)


def _load_env(paths: DataPaths) -> None:
    candidates = [
        Path.cwd() / ".env",
        paths.root / "config" / ".env",
    ]
    for candidate in candidates:
        _load_env_file(candidate)


def load_app_config() -> AppConfig:
    paths = get_data_paths()
    _load_env(paths)
    return AppConfig(
        paths=paths,
        banks=_load_yaml(paths.banks_config),
        rules=_load_yaml(paths.rules_config),
        aliases=_load_yaml_default(paths.aliases_config, {"aliases": []}),
    )
