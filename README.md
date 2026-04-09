# Finance CLI

  _|            _|_|  _|
_|_|_|        _|          _|_|_|
_|_|        _|_|_|_|  _|  _|    _|
  _|_|        _|      _|  _|    _|
_|_|_|        _|      _|  _|    _|
  _|

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
- **Manual accounting entries** in `journal/manual.journal`
- **Generated hledger journals** in `journal/generated/*.journal`
- **Separate data repo** configured with `FIN_DATA_DIR`
- Optional encrypted remote storage for the data repo via `git-crypt`

---

## Current capabilities

- initialize a separate finance data repo
- migrate existing V1 journal data into V2 canonical storage
- sync Investec transactions into canonical JSONL files
- apply categorization rules
- review and manually categorize unknown transactions
- generate `hledger` journals from canonical transaction data
- run `hledger` reports through the CLI
- run basic git workflows against the separate data repo

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
  transactions/
    investec/
      2025.jsonl
      2026.jsonl
  journal/
    main.journal
    manual.journal
    generated/
      investec.journal
  state/
    sync.yaml
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
```

### 4. Review or categorize transactions

```bash
fin review investec
fin categorize investec
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
```

### Review and categorization

```bash
fin review investec
fin categorize investec
fin rules-list
fin rules-apply investec
```

### Reporting

```bash
fin reports bs
fin reports is
fin reports expenses
fin reports unknowns
fin hledger balance
```

### Data repo git helpers

```bash
fin data-status
fin data-pull
fin data-commit -m "Update finance data"
fin data-push
```

---

## Recommended workflow

### Daily workflow

```bash
fin sync investec
fin review investec
fin categorize investec
fin reports bs
fin data-commit -m "Sync latest transactions"
fin data-push
```

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

See also:

- `proposed-plan.md`
- `implementation-roadmap.md`
- `docs/transaction-schema.md`
- `docs/path-config.md`
- `docs/data-repo-layout.md`
- `docs/data-repo-git-workflow.md`
- `docs/migration-from-v1.md`

---

## Status

This project is under active development.

The current implementation focuses on:
- the V2 storage model
- migration from V1
- canonical transaction storage
- generated journal workflows
- a usable day-to-day CLI foundation
