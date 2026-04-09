# Finance V2

V2 of the finance CLI.

## Current focus

- separate code from data
- use `FIN_DATA_DIR`
- store canonical transactions as JSONL
- generate `hledger` journals from canonical data
- keep long-term data in a separate git-crypt-protected data repo

## Development

```bash
cd v2
../.venv/bin/python -m finance.cli.main --help
```

After install, the command should be `fin`.

## Data directory

V2 expects a separate data directory/repo:

```bash
export FIN_DATA_DIR=~/private/finance-data
```

Initialize one:

```bash
../.venv/bin/python -m finance.cli.main init-data ~/private/finance-data
../.venv/bin/python -m finance.cli.main doctor
```

## Current commands

```bash
../.venv/bin/python -m finance.cli.main doctor
../.venv/bin/python -m finance.cli.main init-data ~/private/finance-data
../.venv/bin/python -m finance.cli.main sync investec
../.venv/bin/python -m finance.cli.main journal-build investec
../.venv/bin/python -m finance.cli.main migrate-v1 ../v1
../.venv/bin/python -m finance.cli.main review investec
../.venv/bin/python -m finance.cli.main categorize investec
../.venv/bin/python -m finance.cli.main rules-list
../.venv/bin/python -m finance.cli.main rules-apply investec
../.venv/bin/python -m finance.cli.main reports bs
../.venv/bin/python -m finance.cli.main hledger balance
../.venv/bin/python -m finance.cli.main data-status
../.venv/bin/python -m finance.cli.main data-pull
../.venv/bin/python -m finance.cli.main data-commit -m "Update finance data"
../.venv/bin/python -m finance.cli.main data-push
```
