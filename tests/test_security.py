"""Encryption-coverage check for the data repo."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from finance.services.security import (
    check_encryption_coverage,
    exposed_files,
    git_crypt_patterns,
    is_covered,
    is_sensitive,
)

GITATTRIBUTES = "\n".join(
    [
        "config/** filter=git-crypt diff=git-crypt",
        "transactions/** filter=git-crypt diff=git-crypt",
        "*.pdf filter=git-crypt diff=git-crypt",
        "README.md text",  # not a git-crypt line
    ]
)


def test_git_crypt_patterns_only_returns_git_crypt_lines():
    assert git_crypt_patterns(GITATTRIBUTES) == ["config/**", "transactions/**", "*.pdf"]


def test_is_covered_dir_glob_and_extension():
    patterns = git_crypt_patterns(GITATTRIBUTES)
    assert is_covered("config/rules.yaml", patterns)
    assert is_covered("transactions/tyme/2026.jsonl", patterns)
    assert is_covered("anywhere/statement.pdf", patterns)
    assert not is_covered("investments/ibkr.jsonl", patterns)
    assert not is_covered("imports/tyme/stmt.csv", patterns)


def test_is_sensitive():
    assert is_sensitive("imports/tyme/x.csv")
    assert is_sensitive("investments/ibkr.jsonl")
    assert is_sensitive("anywhere/statement.pdf")
    assert not is_sensitive("README.md")
    assert not is_sensitive(".gitattributes")


def test_exposed_files_flags_uncovered_sensitive():
    tracked = [
        "config/rules.yaml",             # covered
        "transactions/tyme/2026.jsonl",  # covered
        "imports/tyme/stmt.csv",         # sensitive, NOT covered
        "investments/ibkr.jsonl",        # sensitive, NOT covered
        "statement.pdf",                 # covered by *.pdf
        "README.md",                     # not sensitive
    ]
    assert exposed_files(tracked, GITATTRIBUTES) == [
        "imports/tyme/stmt.csv",
        "investments/ibkr.jsonl",
    ]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_check_encryption_coverage_on_a_real_repo(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    (root / ".gitattributes").write_text("transactions/** filter=git-crypt diff=git-crypt\n")
    (root / "transactions").mkdir()
    (root / "transactions" / "2026.jsonl").write_text("{}\n")
    (root / "investments").mkdir()
    (root / "investments" / "ibkr.jsonl").write_text("{}\n")  # sensitive, not covered
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)

    warnings = check_encryption_coverage(root)
    assert len(warnings) == 1
    assert "investments/ibkr.jsonl" in warnings[0]


def test_check_encryption_coverage_ignores_non_git_dir(tmp_path):
    assert check_encryption_coverage(tmp_path) == []
