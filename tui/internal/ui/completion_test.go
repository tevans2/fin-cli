package ui

import (
	"slices"
	"testing"
)

func TestCompletionCandidates(t *testing.T) {
	m := New(nil)
	m.taxonomy = []string{"expenses:groceries", "expenses:lifestyle:bars", "income:salary"}

	m.input.SetValue("")
	_, c, cat := m.completionCandidates()
	if !slices.Contains(c, "cat") || !slices.Contains(c, "uncat") || cat {
		t.Fatalf("top-level commands: %v", c)
	}

	m.input.SetValue("re")
	_, c, _ = m.completionCandidates()
	if !slices.Equal(c, []string{"review"}) {
		t.Fatalf("prefix filter: %v", c)
	}

	m.input.SetValue("cat ")
	_, c, cat = m.completionCandidates()
	if cat || !slices.Equal(c, []string{"add", "rename"}) {
		t.Fatalf("cat subcommands: %v", c)
	}

	m.input.SetValue("cat add ")
	_, c, cat = m.completionCandidates()
	if !cat || len(c) != 3 {
		t.Fatalf("cat add -> full taxonomy: %v cat=%v", c, cat)
	}

	m.input.SetValue("cat add bars")
	_, c, cat = m.completionCandidates()
	if !cat || !slices.Equal(c, []string{"expenses:lifestyle:bars"}) {
		t.Fatalf("cat add filtered: %v", c)
	}

	m.input.SetValue("cat rename income:sal")
	_, c, cat = m.completionCandidates()
	if !cat || !slices.Equal(c, []string{"income:salary"}) {
		t.Fatalf("cat rename old: %v", c)
	}
}

func TestApplyCompletion(t *testing.T) {
	m := New(nil)

	m.input.SetValue("cat add bars")
	m.applyCompletion("expenses:lifestyle:bars", true) // category: no trailing space
	if got := m.input.Value(); got != "cat add expenses:lifestyle:bars" {
		t.Fatalf("category completion: %q", got)
	}

	m.input.SetValue("re")
	m.applyCompletion("review", false) // command: trailing space for more args
	if got := m.input.Value(); got != "review " {
		t.Fatalf("command completion: %q", got)
	}
}
