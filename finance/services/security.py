"""Check that sensitive files in the data repo are git-crypt encrypted.

Raw statements (imports/, *.pdf, *.csv), holdings (investments/), and the
canonical data (config/, transactions/, journal/, state/) should never be
committed in plaintext. This flags tracked files under those paths that no
git-crypt filter in .gitattributes covers.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

SENSITIVE_DIRS = ("config", "transactions", "journal", "state", "investments", "imports")
SENSITIVE_GLOBS = ("*.pdf", "*.csv")


def git_crypt_patterns(gitattributes_text: str) -> list[str]:
    """Path globs in .gitattributes that route through git-crypt."""
    patterns: list[str] = []
    for raw in gitattributes_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "filter=git-crypt" not in line:
            continue
        patterns.append(line.split()[0])
    return patterns


def is_covered(relpath: str, patterns: list[str]) -> bool:
    name = Path(relpath).name
    for pat in patterns:
        if pat.endswith("/**"):
            prefix = pat[:-3]
            if relpath == prefix or relpath.startswith(prefix + "/"):
                return True
        if fnmatch.fnmatch(relpath, pat) or fnmatch.fnmatch(name, pat):
            return True
    return False


def is_sensitive(relpath: str) -> bool:
    top = relpath.split("/", 1)[0]
    if top in SENSITIVE_DIRS:
        return True
    name = Path(relpath).name
    return any(fnmatch.fnmatch(name, glob) for glob in SENSITIVE_GLOBS)


def _tracked_files(root: Path) -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files"], capture_output=True, text=True
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line]


def exposed_files(tracked: list[str], gitattributes_text: str) -> list[str]:
    """Tracked, sensitive files that no git-crypt filter covers (pure/testable)."""
    patterns = git_crypt_patterns(gitattributes_text)
    return sorted(f for f in tracked if is_sensitive(f) and not is_covered(f, patterns))


def check_encryption_coverage(root: Path) -> list[str]:
    """Advisory warnings about plaintext-committed sensitive files. Empty = clean."""
    tracked = _tracked_files(root)
    if tracked is None:
        return []  # not a git repo — nothing is pushed anywhere
    sensitive_tracked = [f for f in tracked if is_sensitive(f)]
    if not sensitive_tracked:
        return []

    gitattributes = root / ".gitattributes"
    if not gitattributes.exists():
        return [
            f"{len(sensitive_tracked)} sensitive file(s) are committed but there is no "
            ".gitattributes — nothing is git-crypt encrypted."
        ]

    exposed = exposed_files(tracked, gitattributes.read_text())
    if not exposed:
        return []
    sample = ", ".join(exposed[:5])
    more = "" if len(exposed) <= 5 else f" (+{len(exposed) - 5} more)"
    return [
        f"{len(exposed)} sensitive file(s) committed in plaintext (not git-crypt covered): {sample}{more}"
    ]
