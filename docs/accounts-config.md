# Accounts Configuration

V2 supports a dedicated account declaration file in hledger format:

```text
config/accounts.journal
```

This file should contain account declarations like:

```journal
account assets:bank:investec:checking
account assets:bank:investec:savings
account expenses:groceries
account income:salary
```

## Purpose

This file is used as the primary source for the account picker in the categorization UI.

It is intentionally stored in hledger style so it stays familiar and easy to edit.

## Recommendation

Keep all accounts you want available in the categorization picker declared here, even if they only appear in manual journals.
