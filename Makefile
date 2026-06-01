VENV    := $(HOME)/.venvs/.fin-venv
FIN     := $(VENV)/bin/fin
BANK    := investec
ACCOUNT := checking
export FIN_DATA_DIR := $(HOME)/private/finance-data

.PHONY: sync categorize run \
        bs is expenses unknowns review \
        spend-month spend-trend top-spend \
        net-worth net-income \
        investments inv-list \
        help

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ { printf "  %-14s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ── data ─────────────────────────────────────────────────────────────────────

sync:        ## Fetch latest transactions from bank (BANK=investec ACCOUNT=checking)
	$(FIN) sync $(BANK) --account $(ACCOUNT)

categorize:  ## Interactively categorize unknown transactions (TUI)
	$(FIN) categorize $(BANK)

run: sync categorize  ## sync then categorize (default workflow)

# ── named reports ─────────────────────────────────────────────────────────────

bs:          ## Balance sheet
	$(FIN) reports bs

is:          ## Income statement
	$(FIN) reports is

expenses:    ## Expense balances
	$(FIN) reports expenses

unknowns:    ## Register of uncategorized transactions
	$(FIN) reports unknowns

review:      ## List unknown transactions without categorizing
	$(FIN) review $(BANK)

# ── cashflow / spending ───────────────────────────────────────────────────────

spend-month: ## Expenses by category, this month (depth-2 tree)
	$(FIN) cashflow bal expenses -M --tree --depth 2 -p "this month"

spend-trend: ## Month-over-month expenses, last 6 months
	$(FIN) cashflow bal expenses -M --tree --depth 2 --begin "6 months ago"

top-spend:   ## Transactions this month sorted by amount
	$(FIN) cashflow reg expenses -M -p "this month" --sort amount

# ── balance / net worth ───────────────────────────────────────────────────────

net-worth:   ## Assets minus liabilities snapshot
	$(FIN) hledger bal assets liabilities --tree

net-income:  ## Net income per month, last 6 months
	$(FIN) cashflow is -M --begin "6 months ago"

# ── investments ───────────────────────────────────────────────────────────────

investments: ## Investment account balances (tree)
	$(FIN) investments bal --tree

inv-list:    ## Latest market value per investment
	$(FIN) investment-list
