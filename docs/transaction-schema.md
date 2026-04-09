# Canonical Transaction Schema

Each imported transaction is stored in JSONL in:

```text
transactions/<bank>/<year>.jsonl
```

## Core fields

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
- `imported_at`

## Optional fields

- `payee`
- `alias`
- `notes`
- `tags`
- `updated_at`
- `source_hash`
- `provider_metadata`

## Alias semantics

`description` is the original normalized bank description.

`alias` is an optional human-friendly label created by the user for clarity.
It should be used by review and journal rendering where appropriate, without overwriting `description`.
