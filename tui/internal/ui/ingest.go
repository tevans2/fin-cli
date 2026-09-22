package ui

import (
	"fmt"
	"strings"

	"fin-tui/internal/api"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
)

// The ingest flow drives one bank at a time off its declared source:
//
//   api        → sync a date range from the provider
//   csv / pdf  → point at a file, dry-run parse, look at the balance chain
//
// Both converge on: land the rows → jump to the uncategorized inbox. A dry-run
// is the commit gate for files, so nothing is written until the chain checks out.

type ingestStep int

const (
	stepBank     ingestStep = iota // choosing which bank
	stepSync                       // api: confirm the pull
	stepFetch                      // email: poll the inbox (default for email banks)
	stepPath                       // csv/pdf: enter the file path
	stepPassword                   // csv/pdf: the file is an encrypted PDF
	stepPreview                    // csv/pdf: dry-run result, confirm commit
)

type ingestState struct {
	active   bool
	busy     bool // a request is in flight
	step     ingestStep
	banks    []api.Bank
	cursor   int
	bank     api.Bank // the selected bank
	account  string
	daysBack int
	ai       bool   // AI fallback for the next parse
	path     string // the file being imported (kept across the password step)
	password string
	pwRetry  bool // the last password attempt was wrong
	preview  *api.ImportResult
	errMsg   string // a dry-run/parse error (e.g. broken balance chain)
}

// ── messages ───────────────────────────────────────────────────────────────────

type banksMsg struct {
	banks []api.Bank
	err   error
}
type previewMsg struct {
	res *api.ImportResult
	err error
}
type ingestDoneMsg struct {
	message string
	err     error
}

// ── update ─────────────────────────────────────────────────────────────────────

func (m *Model) startIngest() tea.Cmd {
	m.ingest = ingestState{active: true, step: stepBank, account: "checking", daysBack: 30, busy: true}
	c := m.client
	return func() tea.Msg { b, err := c.Banks(); return banksMsg{b, err} }
}

func (m Model) runImport(dryRun bool) tea.Cmd {
	c := m.client
	g := m.ingest
	bank, account, path, ai, pw := g.bank.Bank, g.account, g.path, g.ai, g.password
	return func() tea.Msg {
		res, err := c.Import(bank, account, path, dryRun, ai, pw)
		if dryRun {
			return previewMsg{res: res, err: err}
		}
		if err != nil {
			return ingestDoneMsg{err: err}
		}
		return ingestDoneMsg{message: fmt.Sprintf("imported %s: +%d new (%d already present)",
			res.Bank, res.Inserted, res.Skipped)}
	}
}

func (m Model) updateIngest(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	g := &m.ingest
	if g.busy { // ignore input while working, except a hard quit
		if msg.String() == "ctrl+c" {
			m.quit = true
			return m, tea.Quit
		}
		return m, nil
	}

	switch g.step {
	case stepBank:
		switch msg.String() {
		case "esc", "q":
			g.active = false
		case "j", "down":
			if g.cursor < len(g.banks)-1 {
				g.cursor++
			}
		case "k", "up":
			if g.cursor > 0 {
				g.cursor--
			}
		case "enter":
			if g.cursor < len(g.banks) {
				g.bank = g.banks[g.cursor]
				if len(g.bank.Accounts) > 0 {
					g.account = g.bank.Accounts[0]
				}
				switch {
				case g.bank.Source == "api":
					g.step = stepSync
				case g.bank.Email: // inbox polling is the default for email banks
					g.step = stepFetch
				default:
					g.step = stepPath
					m.input.SetValue("")
					m.input.Focus()
					return m, textinput.Blink
				}
			}
		}

	case stepFetch:
		switch msg.String() {
		case "esc":
			g.step = stepBank
		case "f": // fall back to importing a file by path
			g.step = stepPath
			m.input.SetValue("")
			m.input.Focus()
			return m, textinput.Blink
		case "enter":
			g.busy = true
			bank := g.bank.Bank
			c := m.client
			return m, func() tea.Msg {
				r, err := c.Fetch(bank, false)
				if err != nil {
					return ingestDoneMsg{err: err}
				}
				for _, bk := range r.Banks {
					if bk.Error != "" {
						return ingestDoneMsg{err: fmt.Errorf("%s: %s", bk.Bank, bk.Error)}
					}
				}
				if r.Imported == 0 {
					return ingestDoneMsg{message: "no new statements to import"}
				}
				return ingestDoneMsg{message: fmt.Sprintf("fetched %s: +%d rows", bank, r.Imported)}
			}
		}

	case stepSync:
		switch msg.String() {
		case "esc":
			g.step = stepBank
		case "h", "left":
			if g.daysBack > 7 {
				g.daysBack -= 7
			}
		case "l", "right":
			g.daysBack += 7
		case "enter":
			g.busy = true
			bank, account, days := g.bank.Bank, g.account, g.daysBack
			c := m.client
			return m, func() tea.Msg {
				r, err := c.Sync(bank, account, days)
				if err != nil {
					return ingestDoneMsg{err: err}
				}
				return ingestDoneMsg{message: fmt.Sprintf("synced %s: +%d new, %d updated",
					r.Bank, r.Inserted, r.Updated)}
			}
		}

	case stepPath:
		switch msg.String() {
		case "esc":
			g.step = stepBank
			m.input.Blur()
			return m, nil
		case "enter":
			path := strings.TrimSpace(m.input.Value())
			if path == "" {
				return m, nil
			}
			g.path = path
			g.password, g.pwRetry = "", false
			g.busy = true
			return m, m.runImport(true) // dry-run first
		}
		var cmd tea.Cmd
		m.input, cmd = m.input.Update(msg)
		return m, cmd

	case stepPassword:
		switch msg.String() {
		case "esc":
			m.input.EchoMode = textinput.EchoNormal
			g.step = stepPath
			m.input.SetValue(g.path)
			m.input.Focus()
			return m, textinput.Blink
		case "enter":
			g.password = m.input.Value()
			m.input.EchoMode = textinput.EchoNormal
			m.input.SetValue("")
			g.busy = true
			return m, m.runImport(true) // retry the dry-run with the password
		}
		var cmd tea.Cmd
		m.input, cmd = m.input.Update(msg)
		return m, cmd

	case stepPreview:
		switch msg.String() {
		case "esc":
			g.step = stepPath
			g.preview, g.errMsg = nil, ""
			m.input.SetValue(g.path)
			m.input.Focus()
			return m, textinput.Blink
		case "a": // toggle AI fallback and re-parse
			g.ai = !g.ai
			g.busy = true
			return m, m.runImport(true)
		case "enter": // commit (only when we have a clean dry-run)
			if g.preview != nil {
				g.busy = true
				return m, m.runImport(false)
			}
		}
	}
	return m, nil
}
