# TUI spec (Bubble Tea)

A fast, vim-central terminal client for the **day-to-day loop**: import → triage
the inbox → review auto-classifications → verify. Analysis and budgeting live in
the web UI, not here. The TUI is a thin **API client** (Go + Bubble Tea); it never
imports the core. `fin tui` starts the local API and passes `FIN_API_URL` /
`FIN_API_TOKEN` to the binary via env.

## Screens
```
Home ──:cat/:review── Transactions view   (one filtered list; the heart)
  ├── :import   (bank/account/file → run → balance-chain result)
  ├── :verify   (reconciliation table)
  └── :cats     (category management: add / rename; no delete)
```

## The Transactions view (unified)
Two panes: a compact list (left) + focused detail (right). A **scope** filters
what's shown; the action model is identical across scopes, so fixing an old txn
uses the same keys as triaging a new one.

Scopes (set via the `:` command line):
- `:uncat` — uncategorized inbox
- `:review` — auto-classifications awaiting review (`reviewed:false`)
- `:all` — everything (fix past mistakes)
- `:merchant <key>` · `:cat <path>` · `:since <date>` · `/<text>`

List markers: `??` uncategorized · `~` needs review · `✓` confirmed.

## Vim model
- Modes: **normal** (navigate + act) and **insert** (finder, search, split
  amounts, `:` command line). `esc` → normal.
- Navigate: `j/k`, `gg`/`G`, `ctrl-d`/`ctrl-u`, `/` search, `n`/`N` matches.
- Command line `:` — `:uncat` `:review` `:all` `:merchant x` `:cat x` `:since x`
  `:import` `:verify` `:cats` `:q` `:help`.

## Actions on the focused txn (normal mode)
- `Enter` accept recommendation · `1`–`9` pick ranked candidate
- `c` change category (fuzzy finder over the taxonomy) · `s` split
- `.` repeat last category on this txn (rips through same-merchant runs)
- `dd` / `x` **reject**: clear category → uncategorized (works in `:review` to
  reject a guess, and in `:all` to undo a past classification)
- `u` undo last action · `R` make a rule from this merchant→category
- `m` peek merchant history

## Review flow (`:review` only)
- **Confirm-on-scroll**: advancing with `j` confirms the item you leave
  (`reviewed:true`, ✓). Sweep through the good guesses by holding `j`.
- `y` / `space` explicit confirm + advance · `c` correct now · `dd` reject.
- Scroll-confirm is `:review`-only; browsing `:all`/`:uncat` never mutates.

## Category management (`:cats`, lower priority)
Add and rename only — **no delete**. `:cat add expenses:lifestyle:xyz`,
`:cat rename OLD NEW` (token-safe, reuses the core rename). A browse list shows
the taxonomy.

## Speed principles
- Auto-apply confident classifications on entering `:uncat`.
- Optimistic UI (apply immediately, reconcile with API in the background).
- Home shows two counts: *uncategorized: N* and *needs review: N*.
- Deferred: per-rule `auto_confirm` (rules whose matches skip review) — the rule
  model carries the slot; the TUI wires it later.

## Go project shape
```
tui/
  cmd/fin-tui/main.go
  internal/api/       # typed HTTP client (FIN_API_URL / FIN_API_TOKEN)
  internal/ui/        # root model + one model per screen
  internal/ui/txn/    # the list + detail + finder + split components
  internal/styles/    # Lipgloss theme (dark, amounts red/green, confidence bar)
```
Built by `make install` to `~/.local/bin/fin-tui`; `fin tui` execs it. Uses
Bubbles widgets (list, textinput, viewport, help, spinner, table) for reliability.
