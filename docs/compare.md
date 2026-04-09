# Compare Tool

`fin compare investec` compares recent Investec API transactions directly against the locally stored journal/canonical transaction set.

## Purpose

This is useful for:
- checking sync completeness
- spotting missing transactions
- visually aligning API and journal lists
- comparing live API balances with local journal balances
- debugging date/window issues

## Behavior

- left side: straight from Investec API, filtered by the selected compare date mode
- right side: locally stored canonical/journal-side transactions
- summary shows live API current/available balance plus local journal balance at the selected end date
- use `Ctrl-j` / `Ctrl-k` to shift the journal list up/down for alignment

Default compare date mode is:
- `posting` for checking
- `action` for savings

You can override this with `--date-mode posting|action`.

## Commands

```bash
fin compare investec
fin compare investec --account checking --days 14
fin compare investec --account savings --begin 2026-03-20 --end 2026-04-09
fin compare investec --account savings --date-mode action --begin 2026-03-20 --end 2026-04-09
```

## Notes

The current implementation compares against the canonical V2 transaction set (the source used to generate the journal), which is the practical local equivalent of journal-side imported transactions.

For Investec account selection, compare uses:
- `INVESTEC_CHECKING_ACCOUNT_ID` for `--account checking`
- `INVESTEC_SAVINGS_ACCOUNT_ID` for `--account savings`
- falling back to `INVESTEC_ACCOUNT_ID` if the account-specific variable is not set
