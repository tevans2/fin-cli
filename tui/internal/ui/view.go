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
	var right string
	if m.mode == finder {
		right = styles.Pane.Width(detailW).Height(bodyH).Render(m.renderFinder(detailW-2, bodyH))
	} else {
		right = styles.Pane.Width(detailW).Height(bodyH).Render(m.renderDetail(detailW-2, bodyH))
	}
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

func (m Model) footer() string {
	if m.mode == command {
		return styles.Key.Render(":") + m.input.View()
	}
	if m.mode == finder {
		return styles.Help.Render("enter select · ctrl-n/p move · esc cancel")
	}
	help := "j/k move · enter accept · 1-9 pick · c category · x reject · a auto · : cmd · q quit"
	if m.scope == "review" {
		help = "j/k move · y confirm · c correct · x reject · : cmd · q quit"
	}
	line := styles.Help.Render(help)
	if m.msg != "" {
		line = styles.Warn.Render(m.msg) + "   " + line
	}
	return line
}
