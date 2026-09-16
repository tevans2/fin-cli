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
- import CSV/PDF statements from any bank into canonical JSONL files, profile-driven and balance-chain validated
- optional OpenAI fallback for hard PDFs (`--ai-fallback`), with the AI's output still balance-chain validated
- assisted categorization: auto-apply confident matches, recommend the rest, split across categories
- learn merchants from history and validate categories against a taxonomy (`config/categories.yaml`)
- generate `hledger` journals from canonical transaction data
- compare live bank-API transactions against the local journal
- reconcile the ledger against bank statement balances (`fin verify`)
- track investment valuations and generate unrealised gains/losses entries
- build annual budgets and compare actual spending against them
- run `hledger` reports through the CLI
- run basic git workflows against the separate data repo

> **Interfaces:** the Streamlit dashboard and web UI have been removed. The project
> is focused on the backend/core; day-to-day viewing is done through `hledger` and
> the `fin`/`make` report commands, and categorization through the assisted
> `fin categorize` terminal flow. A richer frontend may come later.

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
  install        Install the `fin` CLI on your PATH (uv tool, editable, with AI extra)
  dev            Sync the project venv for development (tests, linting)
  sync           Fetch latest transactions from bank (BANK=investec ACCOUNT=checking)
  categorize     Assisted categorization: auto-apply confident, review the rest
  rules-apply    Auto-categorize transactions by applying rules.yaml
  verify         Reconcile each account's latest statement balance against the ledger
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
- [`uv`](https://docs.astral.sh/uv/) (recommended installer)
- bank API credentials for live sync (optional; statement import needs none)
- a separate directory/repo for finance data

---

## Installation

Install the `fin` CLI onto your PATH with `uv` — no venv to activate or manage:

```bash
uv tool install --editable '.[ai]'   # or: make install
```

`fin` is then available from any directory. `--editable` means code changes take
effect immediately; drop `[ai]` if you don't want the OpenAI PDF fallback.

For development (tests, linting), sync the project environment instead:

```bash
uv sync --extra dev --extra ai       # or: make dev
uv run pytest
```

---

## Quick start

### 1. Initialize a separate data repo

```bash
fin init-data ~/private/finance-data   # also saves the path to ~/.config/fin/config.yaml
fin doctor
```

`init-data` records the data-dir in your config, so you never need to export
`FIN_DATA_DIR`. To point at an existing data repo instead:

```bash
fin config set data-dir ~/private/finance-data
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
fin categorize investec    # auto-apply confident matches, then review the rest
```

### 5. Commit changes in the data repo

```bash
fin data-status
fin data-commit -m "Initial V2 import"
fin data-push
```

---

## Configuration

App settings live in a config directory — `$FIN_CONFIG_DIR`, else
`$XDG_CONFIG_HOME/fin`, else `~/.config/fin`:

- `config.yaml` — settings: `data_dir`, `openai_model`, `ai_attempts`
- `.env` — secrets: `OPENAI_API_KEY`, `<BANK>_DOC_CODE` (loaded automatically)

```bash
fin config show                       # config dir + every setting and its source
fin config set data-dir ~/private/finance-data
fin config set openai-model gpt-4o
fin config get data_dir
fin config path                       # path to config.yaml
fin config edit                       # open it in $EDITOR
```

Every setting can be overridden by an environment variable (which wins), so
`export FIN_DATA_DIR=...` still works — useful for a second or throwaway data repo.

The **data repo** itself (referenced by `data_dir`) holds the per-account data
config, versioned and encrypted with the data:

- `config/banks.yaml`, `config/rules.yaml`, `config/aliases.yaml`, `config/accounts.journal`
- `config/statements/<bank>.yaml` — statement import profiles
- `transactions/<bank>/<year>.jsonl`, `journal/*`, `state/sync.yaml`, `imports/<bank>/*`

---

## Commands

### Setup and validation

```bash
fin --version
fin doctor
fin init-data ~/private/finance-data
fin config show
```

### Migration

```bash
fin migrate-v1 ../v1
```

### Sync and journal generation

```bash
fin sync investec
fin journal-build investec
fin import investec path/to/statement.csv --account savings --dry-run
fin import investec path/to/statement.csv --account savings
fin import fnb path/to/statement.csv --account checking        # any bank, via a profile
fin import acme path/to/statement.pdf --ai-fallback            # OpenAI fallback for hard PDFs
```

Imports are balance-chain validated: if the statement carries a running balance,
a broken chain refuses the import before writing. Onboarding a new no-API account
is a config task — see `docs/statement-import.md`. `--ai-fallback` sends statement
text to OpenAI only when deterministic PDF parsing fails, and validates the result
the same way (needs `OPENAI_API_KEY` and the `[ai]` extra, included by `make install`).

### Categorization

The main flow auto-applies confident categories, then walks the rest with a
pre-filled recommendation (Enter accepts), numbered alternatives, and easy splits:

```bash
fin categorize investec            # auto-apply + assisted review
fin categorize investec --auto     # only apply the confident ones, no prompts
fin categorize investec --dry-run  # preview what would happen
fin categorize investec --ai       # ask OpenAI for a category on unknown merchants
```

In the review, per transaction: **Enter** accepts the recommendation, a **number**
picks an alternative, **c** types a category (taxonomy-validated), **s** splits it
across categories (e.g. `drinks 100`, then `food` for the remainder), **k** skips,
**q** quits. After a manual choice on a non-ambiguous merchant it offers to save a
rule so it auto-applies next time.

Supporting commands:

```bash
fin merchants list --conflicted --sort conf   # merchants worth reviewing
fin merchants show "pizza shed"               # a merchant's categories + example txns
fin categories seed | list | check            # manage the category taxonomy
fin rules-add --merchant "punk bar" --category expenses:lifestyle:drinks
fin rules-list                                 # show active rules
fin review investec                            # just list what's uncategorized
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

### Verification

```bash
fin verify   # reconcile each account's latest statement balance against the ledger
```

`fin verify` reports OK when the ledger balance as of the latest imported row
matches the bank's own running balance, and flags any drift. It exits non-zero
on drift, so it doubles as a scriptable accuracy check.

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
fin categorize investec         # auto-apply confident matches, review the rest
fin verify                      # confirm the ledger matches the bank
fin reports bs
fin data-commit -m "Sync latest transactions"
fin data-push
```

`fin categorize` auto-applies confident matches (rules, or a merchant that's ≥95%
consistent over ≥3 past transactions) and walks you through the rest with
recommendations. Anything you skip stays `expenses:unknown` / `income:unknown`
until the next run.

### Initial migration workflow

```bash
fin init-data ~/private/finance-data   # saves data_dir to config
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

- `docs/statement-import.md` — CSV/PDF statement import, profiles, balance-chain validation, onboarding a new bank
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
