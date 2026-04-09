from __future__ import annotations

import subprocess

from finance.config import load_app_config


class DataRepoError(Exception):
    pass


def _run_git(args: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    config = load_app_config()
    cmd = ["git", *args]
    try:
        return subprocess.run(
            cmd,
            cwd=str(config.paths.root),
            text=True,
            capture_output=capture,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DataRepoError("git is not installed or not on PATH") from exc


def ensure_git_repo() -> None:
    result = _run_git(["rev-parse", "--is-inside-work-tree"], capture=True)
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise DataRepoError("FIN_DATA_DIR is not a git repository. Run 'git init' in the data repo first.")


def git_status() -> int:
    ensure_git_repo()
    result = _run_git(["status"])
    return result.returncode


def git_pull() -> int:
    ensure_git_repo()
    result = _run_git(["pull", "--rebase"])
    return result.returncode


def git_push() -> int:
    ensure_git_repo()
    result = _run_git(["push"])
    return result.returncode


def git_commit(message: str, add_all: bool = True) -> int:
    ensure_git_repo()
    if add_all:
        add_result = _run_git(["add", "."])
        if add_result.returncode != 0:
            return add_result.returncode
    result = _run_git(["commit", "-m", message])
    return result.returncode
