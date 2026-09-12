# Statement import

`fin import` loads a bank statement (CSV or PDF) into canonical JSONL storage.
It is the workflow for any account **without** API access — you download a
statement and import it.

```bash
fin import <bank> path/to/statement.csv --account checking
fin import <bank> path/to/statement.csv --account savings --dry-run
```

`<bank>` is any name (`investec`, `tyme`, `fnb`, …). `--dry-run` parses the file,
runs the balance-chain check, and reports what *would* be inserted without
writing anything.

## The accuracy gate: the balance chain

If the statement has a running-balance column, every import verifies that each
row's balance equals the previous balance plus that row's amount. A mismatch
means a row was misread, dropped, or duplicated, and the import is **refused**
before anything is written — pointing at the exact offending line. This is the
ultimate check that the imported data matches the bank.

Statements without a per-row balance are imported without this check (unless the
profile sets `require_balance_chain: true`, which then refuses the import).

## Onboarding a new account = write a profile

The importer is driven by a **statement profile**, so adding a new bank is a
config task, not a code change. On first import, an unknown bank falls back to a
generic profile that auto-detects common column names — try it and see. To make
imports deterministic, save a profile in your data repo at:

```
config/statements/<bank>-<account>.yaml     # e.g. fnb-checking.yaml
config/statements/<bank>.yaml               # applies to every account
```

Example (`config/statements/fnb-checking.yaml`):

```yaml
name: fnb
id_prefix: fnb
format: csv                    # or: pdf
delimiter: ","
currency: ZAR
order: chronological           # or: newest_first (rows are newest-first in the file)
require_balance_chain: true    # refuse the import if the running balance breaks

# Find the header row by the columns it contains (skips any preamble lines).
# Omit for files whose first row is the header.
header_marker: ["Date", "Description", "Amount", "Balance"]

# Map canonical fields to source columns. Each value is a list of aliases,
# matched case- and space-insensitively. Provide either `amount` (a single
# signed column) or both `debit` and `credit`.
columns:
  date: ["date", "posting date"]
  description: ["description", "narrative"]
  amount: ["amount"]
  # debit: ["money out"]
  # credit: ["money in"]
  balance: ["balance", "running balance"]
  reference: ["reference", "ref"]

# Date formats to try, in order.
date_formats: ["%Y-%m-%d", "%d/%m/%Y"]
```

Canonical fields: `date`, `action_date` (optional secondary date), `description`,
`amount`, `debit`, `credit`, `balance`, `reference`.

## Best CSV format

The easiest format uses a single signed `amount` column:

```
date,description,amount,balance,reference
2026-04-01,Woolworths Food,-350.00,12500.00,TXN123
2026-04-02,Salary,45000.00,57500.00,TXN124
```

- `YYYY-MM-DD` dates are unambiguous.
- Negative amount = money out, positive = money in.
- `R` prefixes and thousands separators are stripped (`R1,500.00` works), and
  `(123)` is read as `-123`.
- Include the running `balance` column whenever the bank offers it — that's what
  lets the balance chain verify the import.

## PDF statements

Generic PDF table detection is unreliable, so a PDF profile parses each line with
a regex whose named groups map onto statement fields. The balance chain then
catches any misread or dropped line.

```yaml
name: acme
id_prefix: acme
format: pdf
date_formats: ["%d/%m/%Y"]
order: chronological
pdf:
  # Named groups: date, description, amount (+ optional direction Cr/Dr/+/-),
  # or debit/credit; plus optional balance, action_date, reference.
  line_regex: >-
    (?P<date>\d{2}/\d{2}/\d{4})\s+(?P<description>.+?)\s+
    (?P<amount>[\d,]+\.\d{2})(?P<direction>-?)\s+(?P<balance>[\d,]+\.\d{2})
```

To build the regex, run `fin import acme statement.pdf --dry-run` and iterate: the
importer extracts text line by line, so match against what the PDF actually
contains. Lines that don't match (headers, page numbers) are ignored; if the
running balance then fails to reconcile, a transaction line was missed and the
import is refused. Multi-line wrapped descriptions aren't handled yet — one
transaction per line.

## Password-protected PDFs

Many banks email encrypted PDFs. Put the password in an environment variable named
`<BANK>_DOC_CODE` (the bank name uppercased, non-alphanumerics become `_`) — e.g.
`INVESTEC_DOC_CODE`, `FNB_DOC_CODE`. It can live in your `.env`:

```
INVESTEC_DOC_CODE=your-statement-password
```

The importer reads it automatically and unlocks the PDF on open. It applies to
both the normal PDF parse and the AI fallback. If a PDF is encrypted and no
matching `<BANK>_DOC_CODE` is set, the import fails with a message telling you
which variable to set.

## AI fallback for stubborn PDFs

When a PDF has no working `pdf.line_regex`, or the parsed rows fail the balance
chain, you can fall back to OpenAI to extract the transactions:

```bash
export OPENAI_API_KEY=sk-...
fin import acme statement.pdf --ai-fallback
```

This only runs when the deterministic parser fails **and** you pass
`--ai-fallback`. What makes it trustworthy: the AI's output is run back through
the **same balance chain** — if the statement shows running balances and the
extraction doesn't reconcile, the import is refused just as a bad regex would be.

- Needs `OPENAI_API_KEY` (set it in your shell or `FIN_DATA_DIR/config/.env`).
- Install the extra: `pip install -e '.[ai]'`.
- Model defaults to `gpt-4o-mini`; override with `OPENAI_MODEL`.

> **Privacy:** `--ai-fallback` sends the statement's text to OpenAI, an external
> service. It is off by default and never runs without the flag. Prefer writing a
> `pdf.line_regex` profile for statements you import regularly, and reserve the AI
> fallback for one-off or awkward layouts.

## Deduplication

Statement rows carry no stable bank id, so imports dedupe on content — (posting
date, amount, normalised description). Re-importing an overlapping statement is
safe and idempotent: rows already stored are skipped and keep their categories;
genuinely repeated transactions (same day, merchant, amount) are disambiguated by
the running balance.

## Where raw files go

The importer copies the raw file into `FIN_DATA_DIR/imports/<bank>/`. Use
`--no-copy-raw` to skip that.

## After importing

```bash
fin rules-apply <bank>     # auto-categorize by rules.yaml
fin review <bank>          # list anything still uncategorized
fin data-commit
```
