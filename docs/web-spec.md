# Web app spec (analysis dashboard)

The **analysis-emphasized** frontend: look at money over time — cashflow, trends,
recurring/subscriptions, spend by merchant/category. Day-to-day triage (import,
categorize, review, fix) stays in the TUI. Like the TUI, the web app is a thin
**API client**; it never imports `finance.*`, it only speaks HTTP+JSON to the
local API.

## Division of labour (a principle, not a limitation)
- **TUI = write.** The inbox loop: import, classify, review, split, verify.
- **Web = read.** Dashboards and exploration over the same data. **v1 is
  read-only** — no mutations from the browser. (We can add light writes later;
  starting read-only keeps the single-writer story simple and the surface small.)

## Running & serving
- `fin web` mirrors `fin tui`: spawn/reuse the ephemeral local API, then open the
  browser at it. One command, one URL, one process.
- **Production:** the FastAPI app serves the built static bundle (Vite output) at
  `/`, so the app is **same-origin** with the API — no CORS, and the bearer token
  is injected by a localhost-only `GET /web-config` (or inlined into `index.html`)
  rather than shipped in the bundle. A catch-all returns `index.html` for unknown
  non-API paths (client-side routing).
- **Dev:** `vite dev` with a proxy for the API paths → hot reload against a running
  `fin serve`. `make web` builds the bundle; `make install` bundles it into the
  package so `fin web` works with zero Node at runtime.

## Stack (proposed)
- **Svelte + Vite**, static SPA (no SSR — data is dynamic and local; SSR buys
  nothing here). Small bundle, minimal boilerplate, good fit for a dashboard.
- **ECharts** for charts (framework-agnostic, strong time-series/financial
  support). TypeScript throughout; a generated/handwritten API client mirroring
  the endpoints and their decimal-string money.
- Alternative if preferred: **React + Vite** (bigger ecosystem, Recharts/ECharts).
  Everything else in this spec is stack-agnostic.

## Pages
```
/            Overview   — this month at a glance
/cashflow    Cashflow   — income/spend/net/savings-rate over time
/trends      Trends     — category spend vs trailing average
/recurring   Recurring  — subscriptions & repeating merchants
/txns        Explorer   — filterable/searchable transaction table
/merchants   Merchants  — spend + category mix per merchant
```

- **Overview** — current-month income / spend / net / savings rate; top categories;
  largest recent transactions; **verify status** (reconciled? drift?); and inbox
  counts (`uncategorized` / `needs review`) as a nudge to open the TUI.
- **Cashflow** — monthly income vs spend (bars) + net/savings-rate (line), range
  picker, per-bank filter. `/analysis/cashflow`.
- **Trends** — categories ranked by change vs their trailing average, depth
  drill-down, per-category sparklines. `/analysis/trends`.
- **Recurring** — cadence, typical amount, active/lapsed, **annualized cost**;
  flags for lapsed or price-changed subscriptions. `/analysis/recurring`.
- **Explorer** — the `/transactions` filters (scope, bank, merchant, category,
  date range, text search) as a fast table; CSV export client-side.
- **Merchants** — `/merchants` + `/merchants/{key}`: spend total, category
  breakdown, recent examples.

## Data & formatting
- Money arrives as decimal **strings**; parse to number only for charting/layout,
  format for display as ZAR. Never round-trip a displayed value back into a write.
- All reads hit the cached-classifier-backed endpoints, so they're instant.

## API: have vs. want
- **Have:** `/status`, `/analysis/cashflow|recurring|trends`, `/transactions`
  (rich filters), `/merchants[/{key}]`, `/verify`, `/taxonomy`, `/banks`.
- **Want (later, for Overview):** `/analysis/overview` (month snapshot + top
  categories + largest txns) and `/analysis/networth` / budget-vs-actual. v1 can
  derive these client-side from existing endpoints; promote to real endpoints once
  the shapes settle.

## Approach / build order
1. Scaffold Vite SPA + `fin web` + API static-serving + token injection — prove
   one page end-to-end (Cashflow) against live data before adding breadth.
2. Shared typed API client + money/format helpers + theme (dark, matches the TUI).
3. Cashflow → Trends → Recurring → Overview → Explorer → Merchants, incrementally.
4. Polish: range/bank filters shared across pages, empty/loading/error states.
