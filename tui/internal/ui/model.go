package ui

import (
	"encoding/json"
	"strings"

	"fin-tui/internal/api"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
)

type mode int

const (
	normal mode = iota
	finder
	command
)

// Model is the whole TUI: a filtered transaction list (scope) with a
// consistent action model. See docs/tui-spec.md.
type Model struct {
	client *api.Client

	scope  string // uncat | review | all
	items  []api.PlanItem
	cursor int
	status api.Status

	mode     mode
	input    textinput.Model
	taxonomy []string
	filtered []string
	fcursor  int

	split       splitState
	splitAdding bool // the finder is picking a category for the split editor

	undo []undoEntry
	redo []undoEntry

	w, h     int
	msg      string
	loading  bool
	showHelp bool
	quit     bool
}

// undoEntry is one reversible action: before/after are full record snapshots
// (opaque JSON from the API); undo restores before, redo restores after.
type undoEntry struct {
	bank   string
	before json.RawMessage
	after  json.RawMessage
	label  string
}

func New(c *api.Client) Model {
	ti := textinput.New()
	ti.Prompt = ""
	return Model{client: c, scope: "uncat", input: ti, loading: true}
}

// ── messages ─────────────────────────────────────────────────────────────────

type plansMsg struct {
	items []api.PlanItem
	err   error
}
type taxMsg struct{ cats []string }
type statusMsg struct{ s api.Status }
type doneMsg struct {
	err      error
	reload   bool
	taxonomy bool
	message  string
}

// ── commands ─────────────────────────────────────────────────────────────────

func (m Model) loadPlan() tea.Cmd {
	c, scope := m.client, m.scope
	return func() tea.Msg {
		items, err := c.Plan(scope)
		return plansMsg{items, err}
	}
}
func (m Model) loadTax() tea.Cmd {
	c := m.client
	return func() tea.Msg { cats, _ := c.Taxonomy(); return taxMsg{cats} }
}
func (m Model) loadStatus() tea.Cmd {
	c := m.client
	return func() tea.Msg { s, _ := c.Status(); return statusMsg{s} }
}

func act(err error, msg string) tea.Cmd {
	return func() tea.Msg { return doneMsg{err: err, reload: false, message: msg} }
}

// mutate records an undo checkpoint for a just-applied change (unless it failed)
// and reports the outcome. Client calls are synchronous, so res is already in hand.
func (m *Model) mutate(bank string, res *api.MutationResult, err error, label string) tea.Cmd {
	if err == nil && res != nil && len(res.Before) > 0 {
		m.undo = append(m.undo, undoEntry{bank: bank, before: res.Before, after: res.After, label: label})
		m.redo = m.redo[:0] // a fresh action invalidates the redo branch
	}
	return act(err, label)
}

func (m Model) undoLast() (tea.Model, tea.Cmd) {
	if len(m.undo) == 0 {
		m.msg = "nothing to undo"
		return m, nil
	}
	e := m.undo[len(m.undo)-1]
	m.undo = m.undo[:len(m.undo)-1]
	m.redo = append(m.redo, e)
	m.loading = true
	c := m.client
	return m, func() tea.Msg {
		return doneMsg{err: c.Restore(e.bank, e.before), reload: true, message: "undo: " + e.label}
	}
}

func (m Model) redoLast() (tea.Model, tea.Cmd) {
	if len(m.redo) == 0 {
		m.msg = "nothing to redo"
		return m, nil
	}
	e := m.redo[len(m.redo)-1]
	m.redo = m.redo[:len(m.redo)-1]
	m.undo = append(m.undo, e)
	m.loading = true
	c := m.client
	return m, func() tea.Msg {
		return doneMsg{err: c.Restore(e.bank, e.after), reload: true, message: "redo: " + e.label}
	}
}

func (m Model) Init() tea.Cmd {
	return tea.Batch(m.loadPlan(), m.loadTax(), m.loadStatus())
}

// current returns the focused plan item, ok=false if the list is empty.
func (m Model) current() (api.PlanItem, bool) {
	if m.cursor < 0 || m.cursor >= len(m.items) {
		return api.PlanItem{}, false
	}
	return m.items[m.cursor], true
}

// removeCurrent drops the focused item (optimistic) and clamps the cursor.
func (m *Model) removeCurrent() {
	if m.cursor < 0 || m.cursor >= len(m.items) {
		return
	}
	m.items = append(m.items[:m.cursor], m.items[m.cursor+1:]...)
	if m.cursor >= len(m.items) {
		m.cursor = len(m.items) - 1
	}
	if m.cursor < 0 {
		m.cursor = 0
	}
}

func (m *Model) filter() {
	q := strings.ToLower(m.input.Value())
	m.filtered = m.filtered[:0]
	for _, c := range m.taxonomy {
		if q == "" || strings.Contains(strings.ToLower(c), q) {
			m.filtered = append(m.filtered, c)
		}
	}
	m.fcursor = 0
}

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.w, m.h = msg.Width, msg.Height
		return m, nil
	case plansMsg:
		m.loading = false
		if msg.err != nil {
			m.msg = "error: " + msg.err.Error()
			return m, nil
		}
		m.items = msg.items
		if m.cursor >= len(m.items) {
			m.cursor = 0
		}
		return m, nil
	case taxMsg:
		m.taxonomy = msg.cats
		return m, nil
	case statusMsg:
		m.status = msg.s
		return m, nil
	case doneMsg:
		if msg.err != nil {
			m.msg = "error: " + msg.err.Error()
			return m, m.loadPlan()
		}
		if msg.message != "" {
			m.msg = msg.message
		}
		cmds := []tea.Cmd{m.loadStatus()}
		if msg.reload {
			cmds = append(cmds, m.loadPlan())
		}
		if msg.taxonomy {
			cmds = append(cmds, m.loadTax())
		}
		return m, tea.Batch(cmds...)
	case tea.KeyMsg:
		if m.showHelp { // help is a modal overlay: any key dismisses it
			m.showHelp = false
			return m, nil
		}
		switch m.mode {
		case finder:
			return m.updateFinder(msg)
		case command:
			return m.updateCommand(msg)
		default:
			if m.split.active {
				return m.updateSplit(msg)
			}
			return m.updateNormal(msg)
		}
	}
	return m, nil
}

func (m Model) updateNormal(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	it, ok := m.current()
	switch msg.String() {
	case "q", "ctrl+c":
		m.quit = true
		return m, tea.Quit
	case "j", "down":
		if m.cursor < len(m.items)-1 {
			m.cursor++
		}
	case "k", "up":
		if m.cursor > 0 {
			m.cursor--
		}
	case "g", "home":
		m.cursor = 0
	case "G", "end":
		m.cursor = len(m.items) - 1
	case "a": // auto-apply confident across all banks
		m.undo, m.redo = nil, nil // bulk change: the per-item undo history no longer holds
		return m, func() tea.Msg {
			err := m.client.Auto()
			return doneMsg{err: err, reload: true, message: "auto-applied confident matches"}
		}
	case "u": // undo the last action
		return m.undoLast()
	case "ctrl+r": // redo
		return m.redoLast()
	case "r": // refresh
		m.loading = true
		return m, m.loadPlan()
	case "?": // help overlay
		m.showHelp = true
		return m, nil
	case "s": // split the focused transaction across categories
		if ok {
			m.startSplit(it)
		}
		return m, nil
	case ":":
		m.mode = command
		m.input.SetValue("")
		m.input.Focus()
		return m, textinput.Blink
	case "c": // category finder
		if ok {
			m.mode = finder
			m.input.SetValue("")
			m.input.Focus()
			m.filter()
			return m, textinput.Blink
		}
	case "x", "d": // reject -> uncategorized
		if ok {
			res, err := m.client.Reject(it.Record.Institution, it.Record.ID)
			m.removeCurrent()
			return m, m.mutate(it.Record.Institution, res, err, "reject")
		}
	case "y", "enter": // accept recommendation (uncat) or confirm (review)
		if !ok {
			return m, nil
		}
		if m.scope == "review" {
			res, err := m.client.Confirm(it.Record.Institution, []string{it.Record.ID})
			m.removeCurrent()
			return m, m.mutate(it.Record.Institution, res, err, "confirm")
		}
		if rec := it.Classification.Recommended; rec != nil {
			res, err := m.client.ApplyCategory(it.Record.Institution, it.Record.ID, *rec)
			m.removeCurrent()
			return m, m.mutate(it.Record.Institution, res, err, "accept "+*rec)
		}
		m.msg = "no recommendation — press c to choose"
	case "1", "2", "3", "4", "5", "6", "7", "8", "9":
		if ok {
			n := int(msg.String()[0] - '1')
			if n < len(it.Classification.Candidates) {
				cat := it.Classification.Candidates[n].Category
				res, err := m.client.ApplyCategory(it.Record.Institution, it.Record.ID, cat)
				m.removeCurrent()
				return m, m.mutate(it.Record.Institution, res, err, "set "+cat)
			}
		}
	}
	return m, nil
}

func (m Model) updateFinder(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "esc":
		m.mode = normal
		if m.splitAdding { // cancel the add; drop the editor if it's still empty
			m.splitAdding = false
			if len(m.split.allocs) == 0 {
				m.split.active = false
			}
		}
		return m, nil
	case "ctrl+n", "down":
		if m.fcursor < len(m.filtered)-1 {
			m.fcursor++
		}
		return m, nil
	case "ctrl+p", "up":
		if m.fcursor > 0 {
			m.fcursor--
		}
		return m, nil
	case "enter":
		if m.splitAdding { // add the chosen category as a new split slot
			m.mode = normal
			m.splitAdding = false
			if m.fcursor < len(m.filtered) {
				m.split.allocs = append(m.split.allocs, splitAlloc{category: m.filtered[m.fcursor]})
				m.split.cursor = len(m.split.allocs) - 1
				m.split.recomputeExact()
			}
			return m, nil
		}
		it, ok := m.current()
		if ok && m.fcursor < len(m.filtered) {
			cat := m.filtered[m.fcursor]
			m.mode = normal
			res, err := m.client.ApplyCategory(it.Record.Institution, it.Record.ID, cat)
			m.removeCurrent()
			return m, m.mutate(it.Record.Institution, res, err, "set "+cat)
		}
		m.mode = normal
		return m, nil
	}
	var cmd tea.Cmd
	m.input, cmd = m.input.Update(msg)
	m.filter()
	return m, cmd
}

func (m Model) updateCommand(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "esc":
		m.mode = normal
		return m, nil
	case "enter":
		raw := strings.TrimSpace(m.input.Value())
		m.mode = normal
		fields := strings.Fields(raw)
		if len(fields) == 0 {
			return m, nil
		}
		switch fields[0] {
		case "q", "quit":
			m.quit = true
			return m, tea.Quit
		case "help", "h", "?":
			m.showHelp = true
			return m, nil
		case "uncat", "review", "all":
			m.scope = fields[0]
			m.cursor = 0
			m.loading = true
			return m, m.loadPlan()
		case "auto":
			m.undo, m.redo = nil, nil
			return m, func() tea.Msg {
				err := m.client.Auto()
				return doneMsg{err: err, reload: true, message: "auto-applied"}
			}
		case "cat":
			return m.categoryCommand(fields[1:])
		default:
			m.msg = "unknown command: " + raw
			return m, nil
		}
	}
	var cmd tea.Cmd
	m.input, cmd = m.input.Update(msg)
	return m, cmd
}

// categoryCommand handles ":cat add <name>" and ":cat rename <old> <new>".
func (m Model) categoryCommand(args []string) (tea.Model, tea.Cmd) {
	if len(args) == 0 {
		m.msg = "usage: :cat add <name>  |  :cat rename <old> <new>"
		return m, nil
	}
	switch args[0] {
	case "add":
		if len(args) != 2 {
			m.msg = "usage: :cat add <category>"
			return m, nil
		}
		name := args[1]
		return m, func() tea.Msg {
			return doneMsg{err: m.client.AddCategory(name), taxonomy: true, message: "added " + name}
		}
	case "rename":
		if len(args) != 3 {
			m.msg = "usage: :cat rename <old> <new>"
			return m, nil
		}
		old, name := args[1], args[2]
		m.undo, m.redo = nil, nil // records change under us; drop stale undo history
		return m, func() tea.Msg {
			return doneMsg{err: m.client.RenameCategory(old, name), reload: true, taxonomy: true,
				message: "renamed " + old + " → " + name}
		}
	default:
		m.msg = "unknown: :cat " + args[0]
		return m, nil
	}
}
