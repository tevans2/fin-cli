# Tyme CSV Import

Tyme currently uses a statement import workflow rather than an API workflow.

## Recommended flow

```bash
# outside fin
pdf -> csv

# inside fin
fin import tyme path/to/statement.csv --account checking --dry-run
fin import tyme path/to/statement.csv --account checking
fin rules-apply tyme
fin categorize tyme
fin journal-build tyme
fin data-commit
```

## Accounts

Use `--account checking` or `--account savings` to match the account the statement is from. This is baked into the transaction ID — importing to the wrong account requires deleting the records from `transactions/tyme/YYYY.jsonl` and re-importing with the correct flag.

## Where raw CSVs are saved

The importer automatically copies the raw CSV to `FIN_DATA_DIR/imports/tyme/`. Use `--no-copy-raw` if you've already placed it there manually.

## Best CSV format

The easiest format uses a single signed `amount` column rather than separate debit/credit columns:

```
date,description,amount,balance,reference
2026-04-01,Woolworths Food,-350.00,12500.00,TXN123
2026-04-02,Salary,45000.00,57500.00,TXN124
```

- Dates as `YYYY-MM-DD` are unambiguous and parsed first
- Negative amount = debit, positive = credit
- `R` prefix and comma-separated thousands are stripped automatically (e.g. `R1,500.00` works)
- Parentheses for negatives also work: `(350.00)` → `-350.00`

## Column detection

The importer tries to auto-detect common columns:

| Field | Accepted header names |
|---|---|
| date | date, transaction date, posting date, value date |
| description | description, details, transaction, narration, merchant |
| amount | amount, transaction amount, signed amount |
| debit | debit, withdrawal, money out |
| credit | credit, deposit, money in |
| balance | balance, running balance, available balance |
| reference | reference, ref, transaction id, id |

If your CSV headers differ, pass explicit overrides:

```bash
fin import tyme statement.csv \
  --date-column "Transaction Date" \
  --description-column "Details" \
  --debit-column "Money Out" \
  --credit-column "Money In"
```

## Features

- CSV import into canonical JSONL
- safe re-import using stable synthetic ids
- preserves manual categorization, aliases, notes, and tags on re-import
- stores a copy of the raw CSV under `imports/tyme/`
- rebuilds `journal/generated/tyme.journal`
- auto-adds `include generated/tyme.journal` to `journal/main.journal`

## Dry run

Use dry-run first:

```bash
fin import tyme statement.csv --account checking --dry-run
```

This prints:
- detected mapping
- rows parsed
- would insert / update / leave unchanged
- date range
- a short preview
