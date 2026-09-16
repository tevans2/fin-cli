package ui

import "testing"

func TestParseCents(t *testing.T) {
	cases := []struct {
		in    string
		want  int64
		valid bool
	}{
		{"100", 10000, true},
		{"100.5", 10050, true},
		{"100.55", 10055, true},
		{"100.555", 10055, true}, // truncated to the cent
		{"-50.00", -5000, true},
		{".50", 50, true},
		{"0", 0, true},
		{"", 0, false},
		{"abc", 0, false},
	}
	for _, c := range cases {
		got, ok := parseCents(c.in)
		if ok != c.valid || (ok && got != c.want) {
			t.Errorf("parseCents(%q) = %d,%v; want %d,%v", c.in, got, ok, c.want, c.valid)
		}
	}
}

// exact mode: typing one amount auto-fills the rest to the cent.
func TestRecomputeExactAutofill(t *testing.T) {
	s := &splitState{total: 25000, allocs: []splitAlloc{
		{category: "a", cents: 10000, locked: true},
		{category: "b"},
	}}
	s.recomputeExact()
	if s.allocs[1].cents != 15000 {
		t.Fatalf("autofill = %d; want 15000", s.allocs[1].cents)
	}
}

// unfixed slots share the remainder evenly, first slot absorbs the odd cent.
func TestRecomputeExactRemainder(t *testing.T) {
	s := &splitState{total: 10001, allocs: []splitAlloc{{category: "a"}, {category: "b"}}}
	s.recomputeExact()
	if s.allocs[0].cents+s.allocs[1].cents != 10001 {
		t.Fatalf("parts don't sum to total: %d + %d", s.allocs[0].cents, s.allocs[1].cents)
	}
	if s.allocs[0].cents != 5001 || s.allocs[1].cents != 5000 {
		t.Fatalf("got %d/%d; want 5001/5000", s.allocs[0].cents, s.allocs[1].cents)
	}
}

// proportion mode: last slot balances and cents always sum to total.
func TestPropCentsBalances(t *testing.T) {
	s := &splitState{kind: splitProp, total: 25000, allocs: []splitAlloc{
		{category: "a", pct: 40},
		{category: "b"}, // balance
	}}
	cents := s.propCents()
	if cents[0] != 10000 || cents[1] != 15000 {
		t.Fatalf("propCents = %v; want [10000 15000]", cents)
	}
	if cents[0]+cents[1] != s.total {
		t.Fatalf("cents don't sum to total")
	}
	if p := s.propPcts(); p[0] != 40 || p[1] != 60 {
		t.Fatalf("propPcts = %v; want [40 60]", p)
	}
}

// bump steps by 5% and refuses to overflow the balance slot.
func TestBumpClamps(t *testing.T) {
	s := &splitState{kind: splitProp, total: 10000, allocs: []splitAlloc{
		{category: "a", pct: 0},
		{category: "b", pct: 0},
		{category: "c"}, // balance
	}}
	s.cursor = 0
	s.bump(5)
	if s.allocs[0].pct != 5 {
		t.Fatalf("bump +5 gave %d; want 5", s.allocs[0].pct)
	}
	s.bump(-5)
	s.bump(-5) // can't go below 0
	if s.allocs[0].pct != 0 {
		t.Fatalf("bump below 0 gave %d; want 0", s.allocs[0].pct)
	}
	// push a to 100, then b can't take more (would exceed 100 total)
	for i := 0; i < 30; i++ {
		s.bump(5)
	}
	if s.allocs[0].pct != 100 {
		t.Fatalf("bump to cap gave %d; want 100", s.allocs[0].pct)
	}
	s.cursor = 1
	s.bump(5)
	if s.allocs[1].pct != 0 {
		t.Fatalf("bump past 100%% total should no-op, got %d", s.allocs[1].pct)
	}
}

func TestFmtCents(t *testing.T) {
	for in, want := range map[int64]string{10000: "100.00", 5: "0.05", 150: "1.50", -5000: "-50.00"} {
		if got := fmtCents(in); got != want {
			t.Errorf("fmtCents(%d) = %q; want %q", in, got, want)
		}
	}
}
