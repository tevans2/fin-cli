# Local API spec

A local HTTP+JSON API that wraps the core services — the single boundary both
frontends (TUI, web) talk to. They never import `finance.*`.

## Running & security
- `fin serve` runs it in the foreground; `fin tui` / `fin web` auto-spawn an
  ephemeral instance and pass the address + token to the client.
- Binds `127.0.0.1:<port>` only. A bearer token (from `~/.config/fin`, or minted
  per run and written to `~/.config/fin/runtime.json`) gates every route.
- Reads/writes the git-crypt-**unlocked** data repo, same as the CLI.
- Single-writer guard: mutations take an in-process lock so a TUI + web can't
  race on a file write.

## Conventions
- JSON in/out. Money is decimal **strings** (never floats). Errors:
  `{"error": "message"}` with a 4xx/5xx status.
- `scope` values on the transactions list: `uncat` | `review` | `all`.

## Endpoints

Classification (priority — backed by an in-process cached history model,
rebuilt only on write, so these are instant):

- `GET  /health` → `{"ok": true}`
- `GET  /status` → `{"uncategorized": n, "needs_review": n, "banks": {...}, "last_import": "...", "verify": "ok|drift"}`
- `GET  /categorize/plan?bank=&scope=uncat` → `[{record, classification}]`
      where `classification = {merchant, recommended, confidence, source, candidates:[{category,share}], auto}`
- `POST /categorize/auto` `{bank}` → `{auto_applied, remaining}` (sets `reviewed:false`)
- `POST /categorize/apply` `{bank, id, category}` | `{bank, id, splits:[{account,amount,notes?}]}`
      → applies, `reviewed:true`, optional `{merchant}` recorded
- `POST /categorize/confirm` `{bank, ids:[...]}` → mark `reviewed:true`
- `POST /categorize/reject` `{bank, id}` → clear category → uncategorized

Transactions & merchants:

- `GET  /transactions?scope=&bank=&merchant=&category=&since=&until=&q=&limit=`
      → `[record]` (the browser)
- `GET  /merchants` · `GET /merchants/{key}` → stats + example transactions

Taxonomy, rules, categories:

- `GET  /taxonomy` → `{categories:[...]}`  (for the finder)
- `POST /categories` `{category}` (add) · `POST /categories/rename` `{old, new}` (token-safe)
- `POST /rules` `{category, merchant?|description_regex?|account?|direction?|amount_lt?|amount_gt?, name?}`

Ops:

- `GET  /verify` → `[{ledger_account, as_of, statement_balance, ledger_balance, difference, ok}]`
- `POST /import` (multipart file or `{path}`) `{bank, account, ai_fallback?, dry_run?}` → import result
- `GET  /analysis/cashflow|trends|recurring` → structured analysis (mainly for web)
- `GET  /budget` · `GET /budget/compare` (web)

## Data-model change
`TransactionRecord.reviewed: bool` (default `true`). Auto-classification
(history/LLM/rule) sets `false`; manual apply and confirm set `true`. Rule model
gains an unused `auto_confirm` slot for a later "skip review" feature.
