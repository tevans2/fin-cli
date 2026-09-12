# Finance CLI

A personal finance CLI built on `hledger` for syncing transactions, categorizing them, and generating reports from a clean canonical transaction store.

## Overview

This project separates **application code** from **personal finance data**.

- The **code repo** contains the CLI, sync logic, migration tools, and journal generation.
- Your **data repo** lives elsewhere and is connected via `FIN_DATA_DIR`.
- Imported transactions are stored as canonical **JSONL** files.
- `hledger` journals are generated from that canonical store.

This keeps the system easier to reason about than a raw-import-first workflow while preserving compatibility with `hledger`.

---

## Core ideas

- **Canonical transaction storage** in `transactions/<bank>/<year>.jsonl`
- **Structured categorization rules** in `config/rules.yaml`
- **Hledger-style account declarations** in `config/accounts.journal`
- **Manual accounting entries** in `journal/manual.journal`
- **Generated hledger journals** in `journal/generated/*.journal`
- **Separate data repo** configured with `FIN_DATA_DIR`
- Optional encrypted remote storage for the data repo via `git-crypt`

---

## Current capabilities

- initialize a separate finance data repo
- migrate existing V1 journal data into V2 canonical storage
- sync Investec transactions into canonical JSONL files
- import Investec and Tyme CSV statements into canonical JSONL files (with balance-chain validation)
- apply categorization rules (`config/rules.yaml`)
- list uncategorized transactions for review
- generate `hledger` journals from canonical transaction data
- compare live bank-API transactions against the local journal
- track investment valuations and generate unrealised gains/losses entries
- build annual budgets and compare actual spending against them
- run `hledger` reports through the CLI
- run basic git workflows against the separate data repo

> **Interfaces:** the interactive TUIs, Streamlit dashboard, and web UI have been
> removed. The project is currently focused on making the backend/core (especially
> classification and analysis) complete and correct before a new frontend is designed.
> Categorization is rules-driven for now (`fin rules-apply`); day-to-day viewing is
> done through `hledger` and the `fin`/`make` report commands.

---

## Project layout

```text
finance/
  cli/
  models/
  providers/
  services/
  storage/
  util/
README.md
pyproject.toml
```

### Separate data repo layout

```text
finance-data/
  config/
    banks.yaml
    rules.yaml
    accounts.journal
  transactions/
    investec/
      2025.jsonl
      2026.jsonl
    tyme/
      2026.jsonl
  investments/
    easyequities.jsonl
    ibkr.jsonl
  journal/
    main.journal
    manual.journal
    generated/
      investec.journal
      tyme.journal
      investments.journal
  imports/
    tyme/
  state/
    sync.yaml
```

---

## Makefile

A `Makefile` is included for common workflows. Run `make help` to list all targets.

```
  help           Show this help
  sync           Fetch latest transactions from bank (BANK=investec ACCOUNT=checking)
  rules-apply    Auto-categorize transactions by applying rules.yaml
  monthly        Full monthly overview through a pager (MONTH="this month")
  budget         Show the budget (YEAR=2027; VIEW=groups|accounts|performance)
  budget-vs      Current spending vs the budget (MONTHS=1)
  bs             Balance sheet
  is             Income statement
  expenses       Expense balances
  unknowns       Register of uncategorized transactions
  review         List unknown transactions without categorizing
  spend-month    Expenses by category, this month (depth-2 tree)
  spend-trend    Month-over-month expenses, last 6 months
  top-spend      Transactions this month sorted by amount
  net-worth      Assets minus liabilities snapshot
  net-income     Net income per month, last 6 months
  investments    Investment account balances (tree)
  inv-list       Latest market value per investment
```

Variables can be overridden on the command line:

```bash
make sync ACCOUNT=savings
make run BANK=tyme ACCOUNT=checking
```

---

## Requirements

- Python 3.11+
- `hledger`
- bank API credentials for live sync
- a separate directory/repo for finance data

---

## Installation

Using your existing virtualenv:

```bash
pip install -e .
```

After installation, the CLI command is:

```bash
fin
```

You can also run directly during development:

```bash
python -m finance.cli.main --help
```

---

## Quick start

### 1. Initialize a separate data repo

```bash
fin init-data ~/private/finance-data
export FIN_DATA_DIR=~/private/finance-data
fin doctor
```

### 2. Migrate existing V1 data

```bash
fin migrate-v1 ../v1
```

### 3. Inspect reports

```bash
fin reports bs
fin reports is
fin compare investec --account checking --begin 2026-03-10 --end 2026-04-09
fin sync investec --account savings --begin 2026-01-01 --end 2026-04-09
```

### 4. Review and categorize transactions

```bash
fin rules-apply investec   # auto-categorize using config/rules.yaml
fin review investec        # list what's still uncategorized
```

### 5. Commit changes in the data repo

```bash
fin data-status
fin data-commit -m "Initial V2 import"
fin data-push
```

---

## Configuration

The app reads all user data through:

```bash
export FIN_DATA_DIR=~/private/finance-data
```

Important paths inside that data repo:

- `config/banks.yaml`
- `config/rules.yaml`
- `config/accounts.journal`
- `imports/<bank>/*`
- `transactions/<bank>/<year>.jsonl`
- `journal/main.journal`
- `journal/manual.journal`
- `journal/generated/<bank>.journal`
- `state/sync.yaml`

---

## Commands

### Setup and validation

```bash
fin doctor
fin init-data ~/private/finance-data
```

### Migration

```bash
fin migrate-v1 ../v1
```

### Sync and journal generation

```bash
fin sync investec
fin journal-build investec
fin import tyme path/to/statement.csv --account checking --dry-run
fin import tyme path/to/statement.csv --account checking
fin import investec path/to/statement.csv --account savings   # balance-chain validated
```

### Review and categorization

```bash
fin rules-list                 # show active rules
fin rules-apply investec       # auto-categorize by rules
fin review investec            # list transactions still uncategorized
```

### Reporting

```bash
fin reports bs
fin reports is
fin reports expenses
fin reports unknowns
fin hledger balance
fin compare investec --account savings --date-mode action --begin 2026-03-01 --end 2026-03-31
```

### Investment tracking

```bash
# Seed baseline (matches manual.journal cost basis entry — no journal entry generated)
fin investment-set easyequities 28100 --baseline --date 2025-12-31

# Record current market value
fin investment-set easyequities 45000
fin investment-set ibkr 2589.91 --currency USD

# View
fin investment-list
fin investment-history easyequities

# Regenerate journal without adding a valuation
fin investment-build
```

See `docs/investments.md` for the full workflow including deposits and selling.

### Budgeting

Budgets live in the data repo as `config/budget-groups.yaml` and `journal/budget-<year>.journal`.

```bash
fin budget show                       # grouped budget (defaults to next year)
fin budget show --accounts            # raw per-account goals
fin budget compare --months 3         # actual spending vs budget over trailing months
fin budget performance --depth 2      # hledger --budget report, by month
```

### Data repo git helpers

```bash
fin data-status
fin data-pull
fin data-commit            # auto datetime message
fin data-commit -m "Update finance data"
fin data-push
```

---

## Recommended workflow

### Daily workflow

```bash
fin sync investec
fin rules-apply investec
fin review investec              # inspect anything still uncategorized
fin reports bs
fin data-commit -m "Sync latest transactions"
fin data-push
```

Transactions that no rule matches stay as `expenses:unknown` / `income:unknown`.
Add or refine rules in `config/rules.yaml` and re-run `fin rules-apply`. A richer
interactive categorization flow is planned once the core is complete.

### Initial migration workflow

```bash
fin init-data ~/private/finance-data
export FIN_DATA_DIR=~/private/finance-data
fin migrate-v1 ../v1
fin reports bs
fin data-commit -m "Initial V2 migration"
```

---

## Data model

Imported transactions are stored as canonical JSONL records, for example:

```json
{
  "id": "41241202603110004778",
  "institution": "investec",
  "source_account": "checking",
  "ledger_account": "assets:bank:investec:checking",
  "date": "2026-03-11",
  "description": "MR TAT EVANS",
  "amount": "-15000.00",
  "currency": "ZAR",
  "category": "assets:bank:investec:savings",
  "category_source": "manual",
  "status": "cleared",
  "imported_at": "2026-04-09T16:39:03Z"
}
```

Generated journals are derived from these canonical records.

---

## Notes on data storage

This repo is intended to stay code-only.

Your real finance data should live in a separate data repo referenced by `FIN_DATA_DIR`.
That data repo can be tracked independently and optionally encrypted remotely with `git-crypt`.

---

## Documentation

- `docs/tyme-import.md` — Tyme CSV import workflow, best CSV format, column detection
- `docs/investments.md` — investment tracking, valuations, cost basis, selling
- `docs/manual-journal.md` — manual journal patterns: opening balances, income deferral, transfers
- `docs/compare.md` — comparing live API transactions against local journal
- `docs/transaction-schema.md` — canonical transaction JSONL schema
- `docs/accounts-config.md` — account declarations

---

## Status

This project is under active development.

The current implementation focuses on:
- the V2 storage model
- migration from V1
- canonical transaction storage
- generated journal workflows
- a usable day-to-day CLI foundation
