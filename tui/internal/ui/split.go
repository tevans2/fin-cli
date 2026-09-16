package ui

import (
	"fmt"
	"strconv"
	"strings"

	"fin-tui/internal/api"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
)

// The split editor partitions one transaction across several categories. Two
// ways to enter the shares (docs/tui-spec.md):
//
//   - exact:      type a cent amount into a slot; the slots you haven't fixed
//                 auto-fill by evenly sharing whatever magnitude is left.
//   - proportion: h/l nudge the focused slot ±5%; the last slot is the balance
//                 and always absorbs the remainder so the amounts sum exactly.
//
// Amounts are held as integer cents so every split lands on the transaction
// magnitude to the cent (the API re-validates this).

type splitKind int

const (
	splitExact splitKind = iota
	splitProp
)

type splitAlloc struct {
	category string
	cents    int64 // exact-mode amount
	locked   bool  // exact-mode: the user typed this amount
	pct      int   // proportion-mode share, a multiple of 5
}

type splitState struct {
	active   bool
	editing  bool // exact-mode amount entry is open
	kind     splitKind
	total    int64 // transaction magnitude, in cents
	rec      api.Record
	merchant *string
	allocs   []splitAlloc
	cursor   int
}

// ── amount helpers ─────────────────────────────────────────────────────────────

func parseCents(s string) (int64, bool) {
	s = strings.TrimSpace(s)
	if s == "" {
		return 0, false
	}
	neg := strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	parts := strings.SplitN(s, ".", 2)
	var whole int64
	if parts[0] != "" {
		w, err := strconv.ParseInt(parts[0], 10, 64)
		if err != nil {
			return 0, false
		}
		whole = w
	}
	var frac int64
	if len(parts) == 2 && parts[1] != "" {
		f := parts[1]
		if len(f) == 1 {
			f += "0"
		}
		if len(f) > 2 {
			f = f[:2]
		}
		v, err := strconv.ParseInt(f, 10, 64)
		if err != nil {
			return 0, false
		}
		frac = v
	}
	total := whole*100 + frac
	if neg {
		total = -total
	}
	return total, true
}

func fmtCents(c int64) string {
	neg := ""
	if c < 0 {
		neg = "-"
		c = -c
	}
	return fmt.Sprintf("%s%d.%02d", neg, c/100, c%100)
}

// ── recompute ──────────────────────────────────────────────────────────────────

// recomputeExact spreads the unfixed magnitude evenly across the slots the user
// hasn't typed an amount for; the first such slot absorbs the rounding cent.
func (s *splitState) recomputeExact() {
	var lockedSum int64
	unlocked := make([]int, 0, len(s.allocs))
	for i := range s.allocs {
		if s.allocs[i].locked {
			lockedSum += s.allocs[i].cents
		} else {
			unlocked = append(unlocked, i)
		}
	}
	if len(unlocked) == 0 {
		return
	}
	rem := s.total - lockedSum
	if rem < 0 {
		rem = 0
	}
	per := rem / int64(len(unlocked))
	for _, i := range unlocked {
		s.allocs[i].cents = per
	}
	s.allocs[unlocked[0]].cents += rem - per*int64(len(unlocked))
}

// propCents turns the proportion shares into cents, the last slot balancing.
func (s *splitState) propCents() []int64 {
	out := make([]int64, len(s.allocs))
	if len(s.allocs) == 0 {
		return out
	}
	var sumOthers int64
	for i := 0; i < len(s.allocs)-1; i++ {
		c := s.total * int64(s.allocs[i].pct) / 100
		out[i] = c
		sumOthers += c
	}
	out[len(s.allocs)-1] = s.total - sumOthers
	return out
}

// propPcts is the displayed percentage per slot (last = balance).
func (s *splitState) propPcts() []int {
	out := make([]int, len(s.allocs))
	if len(s.allocs) == 0 {
		return out
	}
	var others int
	for i := 0; i < len(s.allocs)-1; i++ {
		out[i] = s.allocs[i].pct
		others += s.allocs[i].pct
	}
	out[len(s.allocs)-1] = 100 - others
	return out
}

// bump nudges the focused slot's share, keeping the total within 0..100 so the
// balance slot never goes negative. The balance slot itself isn't adjustable.
func (s *splitState) bump(delta int) {
	n := len(s.allocs)
	if n == 0 || s.cursor == n-1 {
		return
	}
	next := s.allocs[s.cursor].pct + delta
	if next < 0 {
		return
	}
	var others int
	for i := 0; i < n-1; i++ {
		if i != s.cursor {
			others += s.allocs[i].pct
		}
	}
	if others+next > 100 {
		return
	}
	s.allocs[s.cursor].pct = next
}

func (s *splitState) toggleKind() {
	if s.total == 0 {
		return
	}
	if s.kind == splitExact {
		for i := range s.allocs {
			p := int((s.allocs[i].cents*100 + s.total/2) / s.total) // nearest %
			p = ((p + 2) / 5) * 5                                   // nearest 5%
			if p > 100 {
				p = 100
			}
			s.allocs[i].pct = p
		}
		s.kind = splitProp
	} else {
		cents := s.propCents()
		for i := range s.allocs {
			s.allocs[i].cents = cents[i]
			s.allocs[i].locked = true
		}
		s.kind = splitExact
	}
}

// ── update ─────────────────────────────────────────────────────────────────────

func (m *Model) startSplit(it api.PlanItem) {
	total, ok := parseCents(it.Record.Amount)
	if !ok {
		m.msg = "can't parse amount to split"
		return
	}
	if total < 0 {
		total = -total
	}
	m.split = splitState{
		active:   true,
		kind:     splitExact,
		total:    total,
		rec:      it.Record,
		merchant: it.Classification.Merchant,
	}
}

func (m Model) updateSplit(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	s := &m.split
	if s.editing {
		switch msg.String() {
		case "esc":
			s.editing = false
			m.input.Blur()
			return m, nil
		case "enter":
			if cents, ok := parseCents(m.input.Value()); ok && cents >= 0 {
				s.allocs[s.cursor].cents = cents
				s.allocs[s.cursor].locked = true
				s.recomputeExact()
			}
			s.editing = false
			m.input.Blur()
			return m, nil
		}
		var cmd tea.Cmd
		m.input, cmd = m.input.Update(msg)
		return m, cmd
	}

	switch msg.String() {
	case "esc", "q":
		s.active = false
		return m, nil
	case "j", "down":
		if s.cursor < len(s.allocs)-1 {
			s.cursor++
		}
	case "k", "up":
		if s.cursor > 0 {
			s.cursor--
		}
	case "c", "a": // add a category slot (via the finder)
		m.mode = finder
		m.splitAdding = true
		m.input.SetValue("")
		m.input.Focus()
		m.filter()
		return m, textinput.Blink
	case "x", "d": // remove the focused slot
		if len(s.allocs) > 0 {
			s.allocs = append(s.allocs[:s.cursor], s.allocs[s.cursor+1:]...)
			if s.cursor >= len(s.allocs) {
				s.cursor = len(s.allocs) - 1
			}
			if s.cursor < 0 {
				s.cursor = 0
			}
			s.recomputeExact()
		}
	case "tab": // switch between exact amounts and proportions
		s.toggleKind()
	case "i", " ": // exact: type an amount for the focused slot
		if s.kind == splitExact && len(s.allocs) > 0 {
			s.editing = true
			m.input.SetValue("")
			m.input.Focus()
			return m, textinput.Blink
		}
	case "l", "right": // proportion: +5%
		if s.kind == splitProp {
			s.bump(5)
		}
	case "h", "left": // proportion: -5%
		if s.kind == splitProp {
			s.bump(-5)
		}
	case "enter": // apply the split
		return m.saveSplit()
	}
	return m, nil
}

func (m Model) saveSplit() (tea.Model, tea.Cmd) {
	s := &m.split
	if len(s.allocs) < 2 {
		m.msg = "need at least 2 categories to split"
		return m, nil
	}
	var cents []int64
	if s.kind == splitProp {
		cents = s.propCents()
	} else {
		s.recomputeExact()
		cents = make([]int64, len(s.allocs))
		for i := range s.allocs {
			cents[i] = s.allocs[i].cents
		}
	}
	var sum int64
	for _, c := range cents {
		if c <= 0 {
			m.msg = "every category needs a positive amount"
			return m, nil
		}
		sum += c
	}
	if sum != s.total {
		m.msg = fmt.Sprintf("splits total %s, need %s", fmtCents(sum), fmtCents(s.total))
		return m, nil
	}

	splits := make([]api.Split, len(s.allocs))
	for i := range s.allocs {
		splits[i] = api.Split{Account: s.allocs[i].category, Amount: fmtCents(cents[i])}
	}
	bank, id, merchant := s.rec.Institution, s.rec.ID, s.merchant
	s.active = false
	res, err := m.client.ApplySplits(bank, id, splits, merchant)
	m.removeCurrent()
	return m, m.mutate(bank, res, err, "split")
}
