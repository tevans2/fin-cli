# Review TUI / Review UX Spec

## Goal

The review flow is the primary categorization workflow.

`fin sync investec` should ingest transactions and apply only high-confidence hard rules.
Most transactions should remain unknown until manually categorized in review.

## Desired review experience

For each transaction, the UI should show all relevant fields at once:

- date
- amount
- currency
- source account / ledger account
- original description
- alias (if present)
- current category
- category source
- transaction id
- suggested account

## Account selection

The account picker should be fuzzy-searchable and keyboard-first.

It should be prefilled with the most likely account based on:
1. previous manual classifications for the same alias
2. previous manual classifications for the same original description
3. other similar historical classifications
4. fallback current category

## Alias behavior

An alias is a human-friendly label for a transaction description.
It must not overwrite the original description.

Each transaction should store:
- `description` -> original bank/normalized description
- `alias` -> optional user-friendly label

Aliases should be stored durably in `config/aliases.yaml` and applied to future matching transactions.

## Manual categorization behavior

When a user categorizes a transaction in review:
- update the canonical JSONL record
- set `category_source = manual`
- preserve this on future syncs
- rebuild the generated journal

## Sync preservation rule

For already-existing transactions, sync must preserve:
- category
- category_source
- alias
- notes
- tags
- updated_at

Provider refresh must not wipe manual or migrated accounting decisions.
