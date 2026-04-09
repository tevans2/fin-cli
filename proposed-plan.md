# Proposed Plan: Split Code/Data + Encrypted Canonical Transaction Storage

## Goals

- Separate application code from personal financial data.
- Keep remote-stored finance data encrypted.
- Preserve only long-term useful financial information.
- Avoid storing raw API payloads, logs, and other runtime artifacts long-term.
- Keep the system compatible with `hledger` while making the underlying data model cleaner and more durable.

## High-level Direction

The project will move to a **two-repo model**:

1. **Code repo**
   - Contains the CLI/app code, docs, tests, templates, and migration logic.
   - Contains no real personal finance data.

2. **Data repo**
   - Contains the actual long-term finance data.
   - Stored remotely in git with **`git-crypt`** protecting sensitive tracked files.
   - Used locally in plaintext after unlock, which is acceptable for this project.

The application will connect the two using a configured data directory, eg:

```bash
FIN_DATA_DIR=~/private/finance-data
```

The code repo will read/write finance data only through `FIN_DATA_DIR`.

---

## Data Storage Philosophy

Long-term storage should contain only the **useful financial truth** needed to reconstruct and work with the books.

### Keep long-term

- Normalized transaction records
- Categorization/classification decisions
- Manual accounting entries
- Lightweight sync metadata
- Generated journal outputs (at least initially)

### Do not keep long-term

- Raw bank API JSON payloads
- Intermediate normalized CSV files
- Logs
- Temporary import scratch files
- Debugging artifacts
- Other runtime-only state

These runtime artifacts are useful only during processing and troubleshooting and should remain local/ephemeral.

---

## Canonical Long-term Data Model

The canonical long-term finance data will be a **structured transaction store**, not raw imports.

### Canonical tracked data

1. `transactions/<bank>/<year>.jsonl`
2. `config/rules.yaml`
3. `journal/manual.journal`
4. `journal/generated/<bank>.journal`
5. `journal/main.journal`
6. `state/sync.yaml`

### Why this model

This keeps the minimum durable information needed to answer:

- what transaction happened?
- when did it happen?
- how much was it for?
- what account did it affect?
- how was it categorized?
- what manual accounting entries exist?
- can journals and reports be regenerated from this?

If the answer is yes, then the storage is durable and sufficient.

---

## Canonical Transaction Format

Canonical transactions will be stored as **JSON Lines** (`.jsonl`), partitioned by bank and year.

Example path:

```text
transactions/investec/2026.jsonl
```

### Why JSONL

- Structured and machine-friendly
- Good fit for append-oriented transaction history
- Reasonably git-friendly
- Easy to process incrementally
- Better long-term transaction storage than CSV

### Example transaction record

```json
{
  "id": "bank-unique-id",
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
  "notes": null,
  "tags": [],
  "imported_at": "2026-04-09T16:39:03Z"
}
```

### Required ideas in the schema

Each stored transaction should capture:

- a stable transaction id
- source institution/account
- posting date
- cleaned description/payee text
- signed amount and currency
- assigned category/offset account
- how the category was assigned (`manual`, `rule:<name>`, etc.)
- optional notes/tags
- import timestamp

---

## Journals

`hledger` remains the reporting engine, but journal files should become a cleaner representation layer.

### Long-term journal strategy

- `journal/manual.journal` remains the place for hand-written entries.
- `journal/generated/<bank>.journal` is generated from canonical transaction records.
- `journal/main.journal` includes the manual and generated journals.

Example:

```journal
include manual.journal
include generated/investec.journal
```

### Why track generated journals

Initially, generated journals should be tracked because they are:

- directly usable with `hledger`
- easy to inspect
- portable across machines
- a practical secondary representation of the transaction store

Later, they could become purely derived artifacts if desired.

---

## Rules and Categorization

Rules should be stored as structured config, eg:

```text
config/rules.yaml
```

This becomes the long-term home for categorization logic.

Each transaction should also store its assigned category and, where possible, the source of that category assignment.

Example:

- `category: expenses:lifestyle:fast-food`
- `category_source: rule:wa_wa`

This preserves both the result and some explanation of how it was produced.

---

## Lightweight Sync State

A small tracked state file may be kept, eg:

```text
state/sync.yaml
```

This can include:

- last successful sync date
- provider cursor/checkpoint if needed
- schema/import version metadata

This should stay lightweight and useful, not become a dump of runtime state.

---

## Data Repo Layout

Proposed structure:

```text
finance-data/
  config/
    banks.yaml
    rules.yaml
  transactions/
    investec/
      2025.jsonl
      2026.jsonl
    tyme/
      2026.jsonl
  journal/
    manual.journal
    generated/
      investec.journal
      tyme.journal
    main.journal
  state/
    sync.yaml
  .gitattributes
  .gitignore
```

---

## Encryption Model

The data repo will use **`git-crypt`**.

### Expected behavior

- Locally, after unlocking, files are normal plaintext files.
- In git history and on the remote, protected tracked files are encrypted.
- This satisfies the requirement that remote-stored financial data be stored safely.

### Important constraint

`git-crypt` only encrypts **tracked files**.

Therefore:

- canonical long-term files should be tracked
- runtime/temp/log/raw files should be ignored
- sensitive tracked files should be covered by `.gitattributes`

---

## Tracked vs Ignored Policy

### Track and encrypt

- `config/**`
- `transactions/**`
- `journal/**`
- `state/**`

### Ignore

- `logs/`
- `tmp/`
- `raw/`
- `normalized/`
- caches
- scratch files
- debugging artifacts

These ignored paths are operational only and not part of the durable finance record.

---

## Repository Interaction Model

### Code repo

Example:

```text
~/src/finance-app
```

### Data repo

Example:

```text
~/private/finance-data
```

### Runtime connection

```bash
export FIN_DATA_DIR="$HOME/private/finance-data"
```

The app will resolve all user data paths relative to `FIN_DATA_DIR`.

---

## Multi-machine Workflow

On a new machine:

1. Clone the code repo.
2. Clone the private data repo.
3. Unlock the data repo with `git-crypt`.
4. Set `FIN_DATA_DIR` to that clone.
5. Run the CLI normally.

Example:

```bash
git clone git@github.com:you/finance-app.git ~/src/finance-app
git clone git@github.com:you/finance-data.git ~/private/finance-data
cd ~/private/finance-data
git-crypt unlock
export FIN_DATA_DIR=~/private/finance-data
```

This is how the actual personal data and the app coexist across machines.

---

## Processing Lifecycle

### Runtime flow

1. Fetch transactions from the provider
2. Normalize in memory
3. Merge into canonical `transactions/<bank>/<year>.jsonl`
4. Apply rules / preserve manual categorization
5. Generate `journal/generated/<bank>.journal`
6. Use `hledger` on the generated/manual journal layer

### Persistence principle

Only the canonical transaction store and other durable finance files are retained long-term.

Raw payloads, logs, and intermediates remain disposable runtime artifacts.

---

## Migration Direction

The project should gradually move from the current journal/import-artifact-first model toward:

- canonical structured transaction storage in `transactions/**/*.jsonl`
- rules in `config/rules.yaml`
- generated journals derived from canonical transaction records
- manual entries isolated in `journal/manual.journal`
- data location externalized through `FIN_DATA_DIR`
- remote encryption handled by `git-crypt`

---

## Summary

The proposed storage plan is:

- **Separate code from data**
- **Use a private data repo encrypted remotely with `git-crypt`**
- **Store only durable financial truth long-term**
- **Use JSONL as the canonical transaction format**
- **Keep manual journals and generated journals as durable accounting views**
- **Treat raw imports, logs, and intermediate files as disposable runtime artifacts**

This gives a clean, privacy-conscious, git-friendly long-term foundation for the next version of the CLI.
