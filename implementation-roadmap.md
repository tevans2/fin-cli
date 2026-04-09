# V2 Implementation Roadmap

This roadmap turns the proposed V2 architecture into a practical sequence of implementation steps.

It is designed to:
- keep V1 usable during the transition
- establish the new data model first
- minimize rewrites that do not move the storage model forward
- get to a working end-to-end V2 early

---

# 1. V2 Success Criteria

V2 should be considered successful when all of the following are true:

1. The app runs entirely from `v2/`.
2. Real finance data lives outside the code repo in a separate data repo.
3. V2 uses `FIN_DATA_DIR` for all user data.
4. Canonical long-term data is stored as:
   - `transactions/<bank>/<year>.jsonl`
   - `config/rules.yaml`
   - `journal/manual.journal`
   - `journal/generated/*.journal`
   - `state/sync.yaml`
5. Raw API payloads, logs, temp files, and normalized CSVs are not part of long-term tracked storage.
6. The data repo can be protected remotely with `git-crypt`.
7. `hledger` reports work from generated + manual journals.
8. Existing V1 data can be migrated into the V2 canonical store.

---

# 2. Implementation Strategy

The implementation should proceed in this order:

1. **Define the V2 data contract**
2. **Bootstrap the V2 project structure**
3. **Build the config/path layer around `FIN_DATA_DIR`**
4. **Implement canonical transaction storage**
5. **Implement import/sync pipeline into JSONL**
6. **Implement journal generation from canonical transactions**
7. **Implement review/categorization on top of canonical transactions**
8. **Add migration tooling from V1**
9. **Finalize git-crypt data repo workflow**
10. **Polish CLI, tests, and docs**

This order is important. The storage model should come before UX polish.

---

# 3. Phased Roadmap

## Phase 0 — Foundation and Decisions

### Goal
Lock down the V2 contract before coding too much.

### Tasks
- Confirm the canonical tracked files:
  - `transactions/<bank>/<year>.jsonl`
  - `config/rules.yaml`
  - `journal/manual.journal`
  - `journal/generated/<bank>.journal`
  - `journal/main.journal`
  - `state/sync.yaml`
- Confirm that raw/import/log/temp artifacts are runtime-only.
- Confirm `git-crypt` as the data repo encryption model.
- Confirm `FIN_DATA_DIR` as the code/data integration point.
- Decide whether generated journals are tracked initially.
  - Recommended: yes.
- Decide whether V2 will support only Investec first.
  - Recommended: yes.

### Deliverables
- `v2/proposed-plan.md` accepted as the architecture baseline.
- This roadmap accepted as the execution plan.

### Exit criteria
- No open architectural uncertainty about where durable data lives.

---

## Phase 1 — V2 Project Skeleton

### Goal
Create a clean V2 application structure independent from V1.

### Tasks
Create a package-oriented layout under `v2/`, for example:

```text
v2/
  pyproject.toml
  README.md
  finance/
    __init__.py
    cli/
      __init__.py
      main.py
    config.py
    paths.py
    models/
      __init__.py
      transaction.py
      rules.py
      state.py
    storage/
      __init__.py
      jsonl_store.py
      rules_store.py
      journal_store.py
      state_store.py
    providers/
      __init__.py
      base.py
      investec.py
    services/
      __init__.py
      sync.py
      normalize.py
      classify.py
      journal.py
      migrate.py
    util/
      __init__.py
      logging.py
      dates.py
      ids.py
  docs/
```

### Design notes
- Avoid script-per-file architecture from V1.
- Prefer importable services over subprocess orchestration.
- Keep the CLI thin; put real logic into services.

### Deliverables
- Basic package structure in `v2/`
- CLI entrypoint scaffold
- minimal `pyproject.toml`

### Exit criteria
- `python -m finance.cli.main --help` or equivalent works.

---

## Phase 2 — Data Directory + Configuration Layer

### Goal
Make V2 fully data-directory driven.

### Tasks
Implement a path/config layer that:
- reads `FIN_DATA_DIR`
- validates the data directory layout
- resolves canonical paths for:
  - config
  - transactions
  - journals
  - state
  - optional runtime temp paths
- supports a local development fallback if `FIN_DATA_DIR` is unset
  - eg fail with clear message, or use a temp/test dir only

### Recommended API
Examples of resolved paths:
- `data_dir / "config" / "banks.yaml"`
- `data_dir / "config" / "rules.yaml"`
- `data_dir / "transactions" / bank / f"{year}.jsonl"`
- `data_dir / "journal" / "generated" / f"{bank}.journal"`
- `data_dir / "state" / "sync.yaml"`

### Deliverables
- `finance.paths`
- `finance.config`
- data dir validation command, eg `fin doctor`

### Exit criteria
- V2 can start with only `FIN_DATA_DIR` and a valid data directory.

---

## Phase 3 — Canonical Data Schemas

### Goal
Define the exact durable data structures before implementing the pipeline.

### Tasks
Define models for:

#### Transaction record
Recommended fields:
- `id`
- `institution`
- `source_account`
- `ledger_account`
- `date`
- `description`
- `amount`
- `currency`
- `category`
- `category_source`
- `status`
- `notes`
- `tags`
- `imported_at`
- optional: `updated_at`
- optional: `payee`
- optional: `source_hash`

#### Rules model
Rules should support:
- name/id
- match conditions
- output category/account
- priority
- enabled/disabled
- notes

#### Sync state model
Should support:
- last successful sync date per bank
- provider checkpoint/cursor if needed
- schema version
- generated journal metadata if useful

### Deliverables
- typed models in `finance/models/`
- schema docs in `v2/docs/`

### Exit criteria
- Canonical JSONL schema is fixed enough to build against.

---

## Phase 4 — Data Repo Bootstrap Templates

### Goal
Make it easy to create a new V2 data repo.

### Tasks
Provide a command like:

```bash
fin init-data /path/to/finance-data
```

This should create:

```text
finance-data/
  config/
    banks.yaml
    rules.yaml
  transactions/
  journal/
    generated/
    manual.journal
    main.journal
  state/
    sync.yaml
  .gitignore
  .gitattributes
```

Include starter templates for:
- `banks.yaml`
- `rules.yaml`
- `main.journal`
- `sync.yaml`
- `git-crypt`-friendly `.gitattributes`
- runtime-only `.gitignore`

### Deliverables
- `fin init-data`
- data repo templates

### Exit criteria
- A fresh user can create a valid V2 data repo in one command.

---

## Phase 5 — JSONL Transaction Store

### Goal
Implement canonical long-term transaction persistence.

### Tasks
Build a storage layer for transactions that can:
- append new transactions to `transactions/<bank>/<year>.jsonl`
- read all transactions for a bank/year
- query by transaction id
- merge idempotently
- update a transaction category/notes/tags
- preserve stable ordering

### Requirements
- idempotent writes
- stable deduplication by transaction id
- no duplicate transaction records after repeated syncs
- supports rewriting a year file safely when updating classifications

### Suggested behavior
- append-only for new rows where possible
- rewrite whole year file for updates when needed
- keep implementation simple and deterministic

### Deliverables
- `jsonl_store.py`
- tests for merge/dedup/update behavior

### Exit criteria
- V2 can treat JSONL as the canonical transaction store.

---

## Phase 6 — Provider Integration (Investec Only First)

### Goal
Fetch provider transactions into canonical V2 records.

### Tasks
Port the useful provider logic from V1 into a V2 provider layer:
- auth
- fetch recent transactions
- provider-specific parsing
- deterministic normalization into V2 transaction schema

### Important design change from V1
Do **not** persist raw JSON as the primary flow.

Preferred runtime flow:
1. fetch raw response in memory
2. normalize immediately
3. merge canonical transactions into JSONL
4. optionally keep ephemeral debug artifacts only if explicitly requested

### Deliverables
- `providers/base.py`
- `providers/investec.py`
- `services/sync.py`

### Exit criteria
- `fin sync investec` can pull transactions into `transactions/investec/<year>.jsonl`.

---

## Phase 7 — Rules Engine + Categorization

### Goal
Move categorization to structured rules and canonical transaction updates.

### Tasks
Implement a rules engine that:
- loads `config/rules.yaml`
- applies ordered rules to uncategorized transactions
- writes `category` and `category_source`
- leaves unmatched transactions as `expenses:unknown` / `income:unknown` or equivalent

Implement review/update commands that work on canonical transactions, not direct journal mutation.

### Commands to add
Possible V2 commands:
- `fin rules list`
- `fin rules test`
- `fin review`
- `fin categorize`

### Important design decision
V2 categorization should update JSONL transaction records first.
Generated journals should reflect those changes afterward.

### Deliverables
- `rules_store.py`
- `classify.py`
- review/categorize commands

### Exit criteria
- Categorization no longer depends on editing imported journal entries directly.

---

## Phase 8 — Journal Generation

### Goal
Generate `hledger` journals deterministically from canonical transactions.

### Tasks
Implement a journal generator that:
- reads canonical transactions
- renders postings using:
  - source ledger account
  - assigned category account
  - status
  - metadata like transaction id
- writes `journal/generated/<bank>.journal`
- keeps output stable and deterministic

### Journal generation rules
Each imported transaction should produce a reproducible journal entry.

Example concepts:
- first posting: source account
- second posting: category/offset account
- metadata comment: transaction id
- status marker: cleared/pending mapping

### Deliverables
- `services/journal.py`
- command: `fin journal build`

### Exit criteria
- `hledger -f journal/main.journal` works from generated + manual journals.

---

## Phase 9 — Reporting + hledger Integration

### Goal
Restore useful reporting workflows on top of the V2 journal model.

### Tasks
Implement:
- `fin reports ...`
- `fin hledger ...`
- path resolution to use `FIN_DATA_DIR/journal/main.journal`
- safe handling of user `hledger.conf` interaction

### Requirements
- V2 should not depend on V1 layout
- generated/manual journal layout should be the only report source
- import/sync should not be broken by user global hledger config

### Deliverables
- `fin reports`
- `fin hledger`
- `fin doctor` checks for `hledger`

### Exit criteria
- V2 can be used for normal reporting workflows.

---

## Phase 10 — V1 Migration Tooling

### Goal
Provide a deliberate path from existing V1 data into V2 canonical storage.

### Tasks
Implement a migration command, for example:

```bash
fin migrate-v1 --source ../v1 --data-dir ~/private/finance-data
```

It should migrate:
- existing imported transaction data from journals
- manual journal entries
- existing rules where practical
- sync state where practical

### Migration strategy
#### Transaction migration
- parse V1 imported journal entries
- extract transaction id, date, description, amounts, category
- convert into V2 transaction JSONL records

#### Manual journal migration
- copy or split manual entries into `journal/manual.journal`

#### Rules migration
- convert V1 CSV rule logic into `config/rules.yaml`
- manual review likely required

### Deliverables
- migration command
- migration verification report

### Exit criteria
- Existing V1 user can seed a V2 data repo from current data.

---

## Phase 11 — git-crypt Data Repo Workflow

### Goal
Make the separate encrypted data repo operationally easy.

### Tasks
Document and support:
- how to initialize a data repo
- how to run `git-crypt init`
- how to define `.gitattributes`
- how to clone/unlock on a new machine
- how to commit only durable data

### Suggested tracked/encrypted paths
- `config/**`
- `transactions/**`
- `journal/**`
- `state/**`

### Suggested ignored paths
- `logs/`
- `tmp/`
- `raw/`
- `normalized/`
- caches
- scratch files

### Deliverables
- data repo setup docs
- `.gitattributes` template
- `.gitignore` template

### Exit criteria
- Remote-stored finance data is encrypted and workflow is repeatable.

---

## Phase 12 — Testing, Hardening, and Cutover

### Goal
Make V2 reliable enough to become the primary system.

### Tasks
Add tests for:
- path/config loading
- JSONL merge/update behavior
- provider normalization
- rule application
- journal generation
- V1 migration parsing

Add integration tests for:
- sync -> classify -> generate journal
- report commands against generated journal

Define cutover steps:
- freeze V1 data
- run migration
- verify generated journals and balances
- start using V2 as primary

### Deliverables
- test suite
- cutover checklist
- known limitations doc

### Exit criteria
- V2 is trustworthy enough for daily use.

---

# 4. Recommended Milestones

## Milestone A — V2 Skeleton + Data Dir
Includes:
- Phase 1
- Phase 2
- Phase 4

Outcome:
- V2 app exists
- V2 data repo can be initialized
- app resolves `FIN_DATA_DIR`

## Milestone B — Canonical Transaction Store Working
Includes:
- Phase 3
- Phase 5
- Phase 6

Outcome:
- Investec sync writes canonical JSONL transactions

## Milestone C — End-to-End Reporting
Includes:
- Phase 7
- Phase 8
- Phase 9

Outcome:
- sync -> categorize -> generate journal -> hledger reporting works in V2

## Milestone D — Migration + Encrypted Data Repo
Includes:
- Phase 10
- Phase 11

Outcome:
- existing V1 data can be moved into V2
- separate git-crypt data repo is operational

## Milestone E — Production Readiness
Includes:
- Phase 12

Outcome:
- V2 becomes the primary system

---

# 5. Priority Order for Actual Coding

If implementing sequentially, the first coding order should be:

1. project/package skeleton
2. `FIN_DATA_DIR` path layer
3. data repo templates
4. transaction schema definitions
5. JSONL store
6. Investec provider + sync command
7. rules loading/apply logic
8. journal generation
9. reporting commands
10. migration tooling
11. git-crypt docs/templates
12. polish/tests

---

# 6. Things to Avoid in V2

To keep V2 clean, avoid reintroducing these V1 patterns:

- script-per-stage subprocess orchestration as the primary architecture
- raw payloads as long-term storage
- intermediate CSVs as canonical data
- direct journal mutation as the source of categorization truth
- hardcoded project-root-relative data paths
- coupling business logic to the on-disk shape of V1

---

# 7. Suggested First Build Target

The first meaningful V2 target should be:

## "Sync one bank into canonical JSONL and generate one working hledger journal"

That means the first practical slice is:
- `FIN_DATA_DIR`
- Investec provider
- JSONL transaction storage
- rules loading
- generated journal output
- `fin sync investec`
- `fin journal build`

Once that works, everything else becomes much easier.

---

# 8. Final Recommendation

Do not start by rebuilding every CLI feature.

Start by making the **canonical data path real**:

```text
provider fetch -> normalize -> JSONL canonical transactions -> rules -> generated journal -> hledger
```

That is the backbone of V2. Once that exists, the rest of the CLI can be built around it cleanly.
