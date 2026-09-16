# `fin` is expected on PATH (install with `make install`). The data dir comes
# from `fin config` / FIN_DATA_DIR, so it is no longer hardcoded here.
FIN     := fin
BANK    := investec
ACCOUNT := checking
MONTH   := this month

.PHONY: install dev tui sync categorize rules-apply verify \
        bs is expenses unknowns review \
        spend-month spend-trend top-spend monthly \
        net-worth net-income \
        budget budget-vs \
        investments inv-list \
        help

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ { printf "  %-14s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ── setup ─────────────────────────────────────────────────────────────────────

install:     ## Install the `fin` CLI + API on your PATH and build the TUI
	uv tool install --force --editable '.[ai,api]'
	$(MAKE) tui

tui:         ## Build the Go/Bubble Tea TUI to ~/.local/bin/fin-tui
	cd tui && go build -o $(HOME)/.local/bin/fin-tui ./cmd/fin-tui
	@echo "built ~/.local/bin/fin-tui"

dev:         ## Sync the project venv for development (tests, linting)
	uv sync --extra dev --extra ai --extra api

# ── data ─────────────────────────────────────────────────────────────────────

sync:        ## Fetch latest transactions from bank (BANK=investec ACCOUNT=checking)
	$(FIN) sync $(BANK) --account $(ACCOUNT)

categorize:  ## Assisted categorization: auto-apply confident, review the rest (BANK=investec)
	$(FIN) categorize $(BANK)

rules-apply: ## Auto-categorize transactions by applying rules.yaml
	$(FIN) rules-apply $(BANK)

verify:      ## Reconcile each account's latest statement balance against the ledger
	$(FIN) verify

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

monthly:     ## Full monthly overview through a pager (MONTH="this month" or e.g. 2026-07; PAGER overridable)
	@{ \
	  echo "==============================================================="; \
	  echo "  MONTHLY OVERVIEW  -  $(MONTH)"; \
	  echo "==============================================================="; \
	  $(FIN) cashflow is -p "$(MONTH)"; \
	  echo; \
	  echo "----------- SPENDING BY CATEGORY (largest first) --------------"; \
	  $(FIN) cashflow bal expenses --tree --depth 3 -p "$(MONTH)" -S; \
	  echo; \
	  echo "----------- INCOME BY SOURCE ----------------------------------"; \
	  $(FIN) cashflow bal income -p "$(MONTH)" -S; \
	  echo; \
	  echo "----------- BIGGEST EXPENSES (largest last) -------------------"; \
	  $(FIN) cashflow reg expenses -p "$(MONTH)" --sort amount | tail -20; \
	} | $${PAGER:-less -R}

# ── balance / net worth ───────────────────────────────────────────────────────

budget:      ## Show the budget (YEAR=2027; VIEW=groups|accounts|performance)
	$(FIN) budget $(if $(VIEW),$(VIEW),show) $(if $(YEAR),--year $(YEAR),)

budget-vs:   ## Current spending vs the budget (MONTHS=1)
	$(FIN) budget compare $(if $(MONTHS),--months $(MONTHS),) $(if $(YEAR),--year $(YEAR),)

net-worth:   ## Assets minus liabilities snapshot
	$(FIN) hledger bal assets liabilities --tree

net-income:  ## Net income per month, last 6 months
	$(FIN) cashflow is -M --begin "6 months ago"

# ── investments ───────────────────────────────────────────────────────────────

investments: ## Investment account balances (tree)
	$(FIN) investments bal --tree

inv-list:    ## Latest market value per investment
	$(FIN) investment-list
