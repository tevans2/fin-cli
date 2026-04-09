from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import yaml

from .paths import DataPaths, get_data_paths


@dataclass(frozen=True)
class AppConfig:
    paths: DataPaths
    banks: dict
    rules: dict


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_app_config() -> AppConfig:
    paths = get_data_paths()
    return AppConfig(
        paths=paths,
        banks=_load_yaml(paths.banks_config),
        rules=_load_yaml(paths.rules_config),
    )
