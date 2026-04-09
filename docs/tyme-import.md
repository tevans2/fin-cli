# Tyme CSV Import

Tyme currently uses a statement import workflow rather than an API workflow.

## Recommended flow

```bash
# outside fin
pdf -> csv

# inside fin
fin import tyme path/to/statement.csv --account checking --dry-run
fin import tyme path/to/statement.csv --account checking
```

## Features

- CSV import into canonical JSONL
- safe re-import using stable synthetic ids
- preserves manual categorization, aliases, notes, and tags on re-import
- stores a copy of the raw CSV under `imports/tyme/`
- rebuilds `journal/generated/tyme.journal`
- auto-adds `include generated/tyme.journal` to `journal/main.journal`

## Column detection

The importer tries to auto-detect common columns such as:

- date
- description
- amount
- debit / credit
- balance
- reference

If your CSV headers differ, pass explicit overrides such as:

```bash
fin import tyme statement.csv \
  --date-column "Transaction Date" \
  --description-column "Details" \
  --debit-column "Money Out" \
  --credit-column "Money In"
```

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
