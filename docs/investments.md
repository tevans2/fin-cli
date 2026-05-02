# Investment Tracking

Investments are tracked via a combination of `manual.journal` (cash contributions) and the investment CLI (market valuations).

## Account structure

Each investment has one ledger account, e.g. `assets:investments:easyequities`. The value in this account at any time is:

- cash you contributed (recorded in `manual.journal`)
- plus/minus market movements (recorded in `journal/generated/investments.journal`)

Market movements flow through `income:unrealised-gains` — positive market movement credits this account, negative debits it. A single account handles both gains and losses; it goes positive when you're down.

## Setting up a new investment

### 1. Record your cash contributions in manual.journal

```hledger
2026-05-02  EasyEquities cash contributions
    assets:investments:easyequities    28100.00 ZAR
    equity:opening-balances           -28100.00 ZAR
```

Use `equity:opening-balances` because the money was contributed over many years before you started tracking. If the contribution came from a tracked bank account you can use that instead.

### 2. Seed the investment store with a baseline

The baseline tells the CLI what value to start computing deltas from. It generates no journal entry — it just sets the starting point to match what's already in `manual.journal`.

```bash
fin investment-set easyequities 28100 --date 2025-12-31 --baseline --notes "cash contributions baseline"
```

### 3. Record the current market value

```bash
fin investment-set easyequities 45000
```

This computes the delta (`45000 - 28100 = 16900`) and writes it to `investments.journal` against `income:unrealised-gains`.

### 4. Declare the account

Add to `FIN_DATA_DIR/config/accounts.journal`:

```
account assets:investments:easyequities
account income:unrealised-gains
account equity:opening-balances
```

## Ongoing updates

Whenever you check your investment value:

```bash
fin investment-set easyequities 47500
fin data-commit
```

The CLI computes the delta from the last recorded value and appends the entry.

**Important:** if you deposit more cash into the investment, record that in `manual.journal` first, then run `investment-set` with the new total value. The order matters — running `investment-set` before recording the deposit will attribute your cash deposit as market growth.

## Recording a cash deposit

```hledger
2026-06-01  EasyEquities deposit
    assets:investments:easyequities    5000.00 ZAR
    assets:bank:tyme:checking         -5000.00 ZAR
```

Then:

```bash
fin investment-set easyequities 52000
```

## CLI commands

```bash
# Record a valuation (generates delta journal entry)
fin investment-set easyequities 45000
fin investment-set easyequities 45000 --date 2026-04-01   # backdate
fin investment-set easyequities 45000 --notes "Q1 statement"
fin investment-set easyequities 45000 --currency USD       # for foreign accounts

# Seed a baseline (no journal entry generated)
fin investment-set easyequities 28100 --baseline

# Read
fin investment-list                    # latest value per account
fin investment-history easyequities    # all valuations

# Regenerate investments.journal without adding a valuation
fin investment-build
```

Account name convention: `assets:investments:<name>`. Override with `--account assets:investments:something-else`.

## Multiple currencies

IBKR and other foreign accounts work the same way — just pass `--currency USD`:

```bash
fin investment-set ibkr 2315 --baseline --currency USD
fin investment-set ibkr 2589.91 --currency USD
```

## When you sell

Record this manually in `manual.journal`. Example — bought for R28,100, grew to R45,500, sold for R55,000:

```hledger
2026-08-01  Sell EasyEquities
    assets:bank:tyme:checking              55000.00 ZAR
    assets:investments:easyequities       -45500.00 ZAR
    income:unrealised-gains                17400.00 ZAR   ; reverse all paper gains (45500 - 28100)
    income:capital-gains                  -26900.00 ZAR   ; real profit (55000 - 28100)
```

After this entry `income:unrealised-gains` for this investment returns to zero and the real profit lives in `income:capital-gains`.

## Viewing net worth

```bash
fin hledger balance assets liabilities
```

To get a single ZAR total when you hold USD investments, add a price directive to `manual.journal`:

```hledger
P 2026-05-02 USD 18.50 ZAR
```

Then:

```bash
fin hledger balance --value=now
```
