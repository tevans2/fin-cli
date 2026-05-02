# Manual Journal

`FIN_DATA_DIR/journal/manual.journal` is for entries that can't be derived from bank imports — opening balances, investment contributions, transfers between tracked accounts, and income timing adjustments.

## Currency

Always use the `amount CURRENCY` format (e.g. `45000.00 ZAR`, `2315.00 USD`). Do not use the `R` prefix — it creates a separate commodity in hledger and splits your net worth totals.

## Opening balances

Use `equity:opening-balances` for values that existed before you started tracking:

```hledger
2025-12-01  Opening Balances
    assets:bank:investec:checking    5218.40 ZAR
    assets:bank:investec:savings    34405.04 ZAR
    equity:opening-balances        -39623.44 ZAR
```

## Investment cash contributions

See `docs/investments.md` for the full investment workflow. The cost basis entry goes here:

```hledger
2026-05-02  EasyEquities cash contributions
    assets:investments:easyequities    28100.00 ZAR
    equity:opening-balances           -28100.00 ZAR
```

## Income received early (deferral)

When income arrives before the month it belongs to, use a holding liability to defer it.

**Step 1 — categorize the bank transaction to the holding account** (via `fin categorize` or by directly updating the JSONL):

The transaction on e.g. April 28 gets category `liabilities:income-received-early` instead of `income:allowance`.

**Step 2 — add the flip entry in manual.journal dated the first of the correct month:**

```hledger
2026-05-01  Allowance May 2026
    liabilities:income-received-early    7500.00 ZAR
    income:allowance                    -7500.00 ZAR
```

The cash sits in your bank from April 28 but only hits `income:allowance` on May 1. Monthly income reports stay accurate.

## Transfers between tracked accounts

```hledger
2026-03-15  Transfer to savings
    assets:bank:investec:savings     10000.00 ZAR
    assets:bank:investec:checking   -10000.00 ZAR
```

## When you sell an investment

```hledger
2026-08-01  Sell EasyEquities
    assets:bank:tyme:checking              55000.00 ZAR
    assets:investments:easyequities       -45500.00 ZAR
    income:unrealised-gains                17400.00 ZAR
    income:capital-gains                  -26900.00 ZAR
```

See `docs/investments.md` for how to calculate the amounts.
