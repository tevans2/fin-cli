package ui

import (
	"fmt"
	"strings"

	"fin-tui/internal/api"
	"fin-tui/internal/styles"

	"github.com/charmbracelet/lipgloss"
)

func amountStyle(amount string) lipgloss.Style {
	if strings.HasPrefix(amount, "-") {
		return styles.Out
	}
	return styles.In
}

func marker(r api.Record) string {
	switch {
	case r.Category == "expenses:unknown" || r.Category == "income:unknown":
		return "??"
	case !r.Reviewed:
		return "~ "
	default:
		return "✓ "
	}
}

func trunc(s string, n int) string {
	if n <= 0 {
		return ""
	}
	if len(s) <= n {
		return s
	}
	if n <= 1 {
		return s[:n]
	}
	return s[:n-1] + "…"
}

func short(merchant *string, desc string) string {
	if merchant != nil && *merchant != "" {
		return *merchant
	}
	return desc
}

func (m Model) View() string {
	if m.w == 0 {
		return "loading…"
	}
	if m.showHelp {
		return strings.Join([]string{m.header(), m.renderHelp(), m.footer()}, "\n")
	}
	if m.showMerchant {
		return strings.Join([]string{m.header(), m.renderMerchant(), m.footer()}, "\n")
	}
	listW := m.w * 42 / 100
	if listW < 26 {
		listW = 26
	}
	detailW := m.w - listW - 4
	bodyH := m.h - 4
	if bodyH < 3 {
		bodyH = 3
	}

	left := styles.Pane.Width(listW).Height(bodyH).Render(m.renderList(listW-2, bodyH))
	var rightBody string
	switch {
	case m.mode == finder:
		rightBody = m.renderFinder(detailW-2, bodyH)
	case m.split.active:
		rightBody = m.renderSplit(detailW-2, bodyH)
	default:
		rightBody = m.renderDetail(detailW-2, bodyH)
	}
	right := styles.Pane.Width(detailW).Height(bodyH).Render(rightBody)
	body := lipgloss.JoinHorizontal(lipgloss.Top, left, " ", right)

	return strings.Join([]string{m.header(), body, m.footer()}, "\n")
}

func (m Model) header() string {
	scope := styles.Key.Render(":" + m.scope)
	counts := styles.Muted.Render(fmt.Sprintf("uncategorized %d · needs review %d", m.status.Uncategorized, m.status.NeedsReview))
	title := styles.Title.Render("fin")
	return fmt.Sprintf("%s  %s   %s", title, scope, counts)
}

func (m Model) renderList(w, h int) string {
	if m.loading {
		return styles.Muted.Render("loading…")
	}
	if len(m.items) == 0 {
		return styles.Ok.Render("inbox zero ✨")
	}
	// scroll window around the cursor
	start := 0
	if m.cursor >= h {
		start = m.cursor - h + 1
	}
	end := start + h
	if end > len(m.items) {
		end = len(m.items)
	}
	var b strings.Builder
	for i := start; i < end; i++ {
		r := m.items[i].Record
		amt := amountStyle(r.Amount).Render(fmt.Sprintf("%10s", r.Amount))
		line := fmt.Sprintf("%s %s  %s  %s", marker(r), r.Date[5:], amt, trunc(short(r.Merchant, r.Description), w-26))
		if i == m.cursor {
			b.WriteString(styles.Sel.Width(w).Render("› " + line))
		} else {
			b.WriteString("  " + line)
		}
		b.WriteString("\n")
	}
	return b.String()
}

func (m Model) renderDetail(w, h int) string {
	it, ok := m.current()
	if !ok {
		return styles.Muted.Render("nothing to review")
	}
	r, c := it.Record, it.Classification
	var b strings.Builder
	merchant := "?"
	if c.Merchant != nil {
		merchant = *c.Merchant
	}
	b.WriteString(styles.Title.Render(r.Date) + "   " + amountStyle(r.Amount).Render(r.Amount+" "+r.Currency) + "\n")
	b.WriteString(styles.Muted.Render("merchant: ") + merchant + "\n")
	b.WriteString(styles.Dim.Render(trunc(r.Description, w)) + "\n\n")

	if m.scope == "review" {
		b.WriteString(styles.Muted.Render("current:  ") + r.Category + styles.Dim.Render("  ["+r.Source+"]") + "\n")
	} else {
		rec := "(none)"
		if c.Recommended != nil {
			rec = *c.Recommended
		}
		b.WriteString(styles.Muted.Render("recommend: ") + styles.Ok.Render(rec) +
			styles.Dim.Render(fmt.Sprintf("  [%s %.0f%%]", c.Source, c.Confidence*100)) + "\n")
	}
	if len(c.Candidates) > 0 {
		b.WriteString("\n" + styles.Muted.Render("candidates:") + "\n")
		for i, cand := range c.Candidates {
			if i >= 9 {
				break
			}
			b.WriteString(fmt.Sprintf("  %s %s %s\n",
				styles.Key.Render(fmt.Sprintf("%d", i+1)),
				trunc(cand.Category, w-10),
				styles.Dim.Render(fmt.Sprintf("%.0f%%", cand.Share*100))))
		}
	}
	return b.String()
}

func (m Model) renderFinder(w, h int) string {
	var b strings.Builder
	b.WriteString(styles.Muted.Render("category ▸ ") + m.input.View() + "\n\n")
	max := h - 3
	for i, cat := range m.filtered {
		if i >= max {
			break
		}
		if i == m.fcursor {
			b.WriteString(styles.Sel.Width(w).Render("› "+trunc(cat, w-2)) + "\n")
		} else {
			b.WriteString("  " + trunc(cat, w-2) + "\n")
		}
	}
	return b.String()
}

// renderHelp draws the full-screen keybinding reference (toggled with ? or :help).
func (m Model) renderHelp() string {
	bodyH := m.h - 4
	if bodyH < 3 {
		bodyH = 3
	}
	k := func(s string) string { return styles.Key.Render(s) }

	type row struct{ keys, desc string }
	section := func(title string, rows []row) string {
		var b strings.Builder
		b.WriteString(styles.Title.Render(title) + "\n")
		for _, r := range rows {
			b.WriteString(fmt.Sprintf("  %-14s %s\n", k(r.keys), styles.Muted.Render(r.desc)))
		}
		return b.String()
	}

	nav := section("navigate", []row{
		{"j / k", "move down / up"},
		{"g / G", "jump to first / last"},
		{"u", "undo the last action"},
		{"ctrl-r", "redo"},
		{"r", "refresh the list"},
	})
	actions := section("act on the focused transaction", []row{
		{"enter", "accept the recommendation (confirm, in :review)"},
		{"1 – 9", "pick a ranked candidate"},
		{"c", "choose a category (fuzzy finder)"},
		{"s", "split across categories (amount or %)"},
		{"m", "peek at this merchant's history"},
		{"x", "reject → back to uncategorized"},
		{"a", "auto-apply all confident matches"},
	})
	commands := section("commands  (press : then type)", []row{
		{":uncat", "uncategorized inbox"},
		{":review", "auto-classified (j confirms + advances)"},
		{":all", "every transaction"},
		{":auto", "auto-apply confident matches"},
		{":cat add <name>", "add a category"},
		{":cat rename <a> <b>", "rename a category"},
		{":help", "show this help"},
		{":q", "quit"},
	})
	finderHelp := section("category finder", []row{
		{"type", "filter categories"},
		{"ctrl-n / ctrl-p", "move down / up"},
		{"enter", "apply the selected category"},
		{"esc", "cancel"},
	})
	splitHelp := section("split editor  (s)", []row{
		{"c", "add a category slot"},
		{"i", "type an exact amount (rest auto-fills)"},
		{"h / l", "proportion ∓/± 5%"},
		{"tab", "toggle amount / proportion"},
		{"x", "remove slot   ·   enter apply   ·   esc cancel"},
	})

	left := lipgloss.JoinVertical(lipgloss.Left, nav, "", actions, "", splitHelp)
	right := lipgloss.JoinVertical(lipgloss.Left, commands, "", finderHelp)
	cols := lipgloss.JoinHorizontal(lipgloss.Top, left, "    ", right)

	dismiss := styles.Dim.Render("press ? or esc to close")
	page := lipgloss.JoinVertical(lipgloss.Left, cols, "", dismiss)
	return styles.Pane.Width(m.w - 2).Height(bodyH).Render(page)
}

// renderMerchant is the modal peek at a merchant's history (toggled with m).
func (m Model) renderMerchant() string {
	d := m.merchant
	bodyH := m.h - 4
	if bodyH < 3 {
		bodyH = 3
	}
	if d == nil {
		return styles.Pane.Width(m.w - 2).Height(bodyH).Render(styles.Muted.Render("no merchant"))
	}
	var b strings.Builder
	b.WriteString(styles.Title.Render(d.Merchant) + "  " +
		styles.Muted.Render(fmt.Sprintf("%d transactions", d.Samples)) + "\n\n")

	b.WriteString(styles.Muted.Render("categories") + "\n")
	for _, r := range d.Breakdown {
		b.WriteString(fmt.Sprintf("  %-32s %s  %s\n",
			trunc(r.Category, 32),
			styles.Key.Render(fmt.Sprintf("%3.0f%%", r.Share*100)),
			styles.Dim.Render(fmt.Sprintf("×%d", r.Count))))
	}

	b.WriteString("\n" + styles.Muted.Render("recent") + "\n")
	max := bodyH - len(d.Breakdown) - 6
	for i, r := range d.Examples {
		if i >= max || i >= 12 {
			break
		}
		amt := amountStyle(r.Amount).Render(fmt.Sprintf("%10s", r.Amount))
		b.WriteString(fmt.Sprintf("  %s  %s  %s\n", r.Date, amt, styles.Dim.Render(trunc(r.Category, 28))))
	}

	page := b.String() + "\n" + styles.Dim.Render("press any key to close")
	return styles.Pane.Width(m.w - 2).Height(bodyH).Render(page)
}

func (m Model) splitHelp() string {
	if m.split.editing {
		return "type amount · enter set · esc cancel"
	}
	if m.split.kind == splitProp {
		return "j/k move · h/l ±5% · c add · x remove · tab exact · enter apply · esc cancel"
	}
	return "j/k move · i amount · c add · x remove · tab % · enter apply · esc cancel"
}

func (m Model) renderSplit(w, h int) string {
	s := m.split
	kind := "exact"
	if s.kind == splitProp {
		kind = "proportion"
	}
	var b strings.Builder
	src := "?"
	if s.merchant != nil && *s.merchant != "" {
		src = *s.merchant
	}
	b.WriteString(styles.Title.Render("split "+fmtCents(s.total)) + "  " +
		styles.Key.Render("["+kind+"]") + "  " + styles.Dim.Render(src) + "\n\n")

	if len(s.allocs) == 0 {
		b.WriteString(styles.Muted.Render("press c to add a category") + "\n")
		return b.String()
	}

	var cents []int64
	var pcts []int
	if s.kind == splitProp {
		cents = s.propCents()
		pcts = s.propPcts()
	} else {
		cents = make([]int64, len(s.allocs))
		for i := range s.allocs {
			cents[i] = s.allocs[i].cents
		}
	}

	var sum int64
	catW := w - 24
	if catW < 8 {
		catW = 8
	}
	for i, a := range s.allocs {
		sum += cents[i]
		tag := ""
		if s.kind == splitExact && !a.locked {
			tag = styles.Dim.Render(" auto")
		}
		if s.kind == splitProp && i == len(s.allocs)-1 {
			tag = styles.Dim.Render(" bal")
		}
		mid := ""
		if s.kind == splitProp {
			mid = styles.Key.Render(fmt.Sprintf("%3d%% ", pcts[i]))
		}
		line := fmt.Sprintf("%-*s %s%9s%s", catW, trunc(a.category, catW), mid, fmtCents(cents[i]), tag)
		if i == s.cursor {
			b.WriteString(styles.Sel.Width(w).Render("› "+line) + "\n")
		} else {
			b.WriteString("  " + line + "\n")
		}
	}

	b.WriteString("\n")
	if s.editing {
		b.WriteString(styles.Muted.Render("amount ▸ ") + m.input.View() + "\n")
	}
	rem := s.total - sum
	switch {
	case len(s.allocs) < 2:
		b.WriteString(styles.Muted.Render("add another category to split"))
	case rem == 0:
		b.WriteString(styles.Ok.Render("balanced ✓  enter to apply"))
	default:
		b.WriteString(styles.Warn.Render("remaining " + fmtCents(rem)))
	}
	return b.String()
}

func (m Model) footer() string {
	if m.mode == command {
		return styles.Key.Render(":") + m.input.View()
	}
	if m.mode == finder {
		return styles.Help.Render("enter select · ctrl-n/p move · esc cancel")
	}
	if m.split.active {
		return styles.Help.Render(m.splitHelp())
	}
	help := "j/k move · enter accept · 1-9 pick · c cat · s split · m peek · x reject · a auto · u undo · ? help · q quit"
	if m.scope == "review" {
		help = "j confirm+next · k up · c correct · s split · m peek · x reject · u undo · ? help · q quit"
	}
	line := styles.Help.Render(help)
	if m.msg != "" {
		line = styles.Warn.Render(m.msg) + "   " + line
	}
	return line
}
