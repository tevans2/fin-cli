from __future__ import annotations

from pathlib import Path


class AccountsStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[str]:
        if not self.path.exists():
            return []
        accounts: list[str] = []
        with open(self.path) as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith(";") or line.startswith("#"):
                    continue
                if line.startswith("account "):
                    account = line[len("account "):].strip()
                    if account:
                        accounts.append(account)
        return accounts

    def save(self, accounts: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        unique_accounts = sorted(dict.fromkeys(a.strip() for a in accounts if a.strip()))
        content = "; Account declarations for picker and journal ergonomics\n\n"
        content += "\n".join(f"account {account}" for account in unique_accounts)
        content += "\n"
        self.path.write_text(content)
