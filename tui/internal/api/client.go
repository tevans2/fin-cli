package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"time"
)

// Client talks to the local fin API. Address + token come from the env the
// `fin tui` launcher sets (FIN_API_URL / FIN_API_TOKEN).
type Client struct {
	base  string
	token string
	http  *http.Client
	// long is for ingestion (sync / import), which can run well past the
	// interactive timeout — AI PDF extraction especially.
	long *http.Client
}

func New() *Client {
	base := os.Getenv("FIN_API_URL")
	if base == "" {
		base = "http://127.0.0.1:8765"
	}
	return &Client{
		base:  base,
		token: os.Getenv("FIN_API_TOKEN"),
		http:  &http.Client{Timeout: 20 * time.Second},
		long:  &http.Client{Timeout: 5 * time.Minute},
	}
}

func (c *Client) do(method, path string, body any, out any) error {
	return c.doWith(c.http, method, path, body, out)
}

func (c *Client) doWith(hc *http.Client, method, path string, body any, out any) error {
	var r io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		r = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, c.base+path, r)
	if err != nil {
		return err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	resp, err := hc.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		var e struct {
			Detail string `json:"detail"`
			Error  string `json:"error"`
		}
		_ = json.Unmarshal(data, &e)
		msg := e.Detail
		if msg == "" {
			msg = e.Error
		}
		if msg == "" {
			msg = string(data)
		}
		return fmt.Errorf("%s", msg)
	}
	if out != nil {
		return json.Unmarshal(data, out)
	}
	return nil
}

// ── types (mirror the API JSON) ──────────────────────────────────────────────

type Record struct {
	ID          string  `json:"id"`
	Institution string  `json:"institution"`
	Date        string  `json:"date"`
	Amount      string  `json:"amount"`
	Currency    string  `json:"currency"`
	Description string  `json:"description"`
	Category    string  `json:"category"`
	Merchant    *string `json:"merchant"`
	Reviewed    bool    `json:"reviewed"`
	Source      string  `json:"category_source"`
	Notes       *string `json:"notes"`
}

type Candidate struct {
	Category string  `json:"category"`
	Share    float64 `json:"share"`
	Count    int     `json:"count"`
}

type Classification struct {
	Merchant    *string     `json:"merchant"`
	MerchantKey *string     `json:"merchant_key"`
	Recommended *string     `json:"recommended"`
	Confidence  float64     `json:"confidence"`
	Source      string      `json:"source"`
	Auto        bool        `json:"auto"`
	Candidates  []Candidate `json:"candidates"`
}

type BreakdownRow struct {
	Category string  `json:"category"`
	Count    int     `json:"count"`
	Share    float64 `json:"share"`
}

type MerchantDetail struct {
	Key       string         `json:"key"`
	Merchant  string         `json:"merchant"`
	Samples   int            `json:"samples"`
	Breakdown []BreakdownRow `json:"breakdown"`
	Examples  []Record       `json:"examples"`
}

type PlanItem struct {
	Record         Record         `json:"record"`
	Classification Classification `json:"classification"`
}

type Status struct {
	Uncategorized int `json:"uncategorized"`
	NeedsReview   int `json:"needs_review"`
}

// ── calls ────────────────────────────────────────────────────────────────────

func (c *Client) Plan(scope string) ([]PlanItem, error) {
	var out []PlanItem
	q := url.Values{}
	q.Set("scope", scope)
	return out, c.do("GET", "/categorize/plan?"+q.Encode(), nil, &out)
}

func (c *Client) Status() (Status, error) {
	var s Status
	return s, c.do("GET", "/status", nil, &s)
}

func (c *Client) Taxonomy() ([]string, error) {
	var o struct {
		Categories []string `json:"categories"`
	}
	err := c.do("GET", "/taxonomy", nil, &o)
	return o.Categories, err
}

func (c *Client) Auto() error {
	return c.do("POST", "/categorize/auto", map[string]any{}, nil)
}

// MutationResult carries the full before/after record snapshots a mutation
// returns, so the caller can undo (restore before) or redo (restore after).
type MutationResult struct {
	Before json.RawMessage `json:"before"`
	After  json.RawMessage `json:"after"`
}

func (c *Client) ApplyCategory(bank, id, category string) (*MutationResult, error) {
	var out MutationResult
	err := c.do("POST", "/categorize/apply", map[string]any{"bank": bank, "id": id, "category": category}, &out)
	return &out, err
}

// Split is one allocation of a transaction to a category (positive magnitude).
type Split struct {
	Account string `json:"account"`
	Amount  string `json:"amount"`
}

func (c *Client) ApplySplits(bank, id string, splits []Split, merchant *string) (*MutationResult, error) {
	body := map[string]any{"bank": bank, "id": id, "splits": splits}
	if merchant != nil {
		body["merchant"] = *merchant
	}
	var out MutationResult
	err := c.do("POST", "/categorize/apply", body, &out)
	return &out, err
}

func (c *Client) Confirm(bank string, ids []string) (*MutationResult, error) {
	var out struct {
		Before []json.RawMessage `json:"before"`
		After  []json.RawMessage `json:"after"`
	}
	if err := c.do("POST", "/categorize/confirm", map[string]any{"bank": bank, "ids": ids}, &out); err != nil {
		return nil, err
	}
	res := &MutationResult{}
	if len(out.Before) > 0 {
		res.Before = out.Before[0]
	}
	if len(out.After) > 0 {
		res.After = out.After[0]
	}
	return res, nil
}

func (c *Client) Reject(bank, id string) (*MutationResult, error) {
	var out MutationResult
	err := c.do("POST", "/categorize/reject", map[string]any{"bank": bank, "id": id}, &out)
	return &out, err
}

// Restore writes a full record snapshot back in place — the undo/redo primitive.
func (c *Client) Restore(bank string, record json.RawMessage) error {
	return c.do("POST", "/categorize/restore", map[string]any{"bank": bank, "record": record}, nil)
}

// Note sets (or clears, with "") a free-text note on a transaction.
func (c *Client) Note(bank, id, note string) (*MutationResult, error) {
	var out MutationResult
	err := c.do("POST", "/transactions/note", map[string]any{"bank": bank, "id": id, "note": note}, &out)
	return &out, err
}

// ── ingestion ────────────────────────────────────────────────────────────────

type Bank struct {
	Bank     string   `json:"bank"`
	Name     string   `json:"name"`
	Currency string   `json:"currency"`
	Source   string   `json:"source"` // api | csv | pdf
	Accounts []string `json:"accounts"`
	Email    bool     `json:"email"` // has an IMAP inbox to poll
}

func (c *Client) Banks() ([]Bank, error) {
	var out []Bank
	return out, c.do("GET", "/banks", nil, &out)
}

type FetchFile struct {
	File     string `json:"file"`
	Ok       bool   `json:"ok"`
	Inserted int    `json:"inserted"`
	Already  int    `json:"already"`
	Verified bool   `json:"verified"`
	Error    string `json:"error"`
}
type FetchBankResult struct {
	Bank     string      `json:"bank"`
	Mailbox  string      `json:"mailbox"`
	Scanned  int         `json:"scanned"`
	Imported int         `json:"imported"`
	Error    string      `json:"error"`
	Files    []FetchFile `json:"files"`
}
type FetchResult struct {
	Imported int               `json:"imported"`
	Banks    []FetchBankResult `json:"banks"`
}

func (c *Client) Fetch(bank string, dryRun bool) (*FetchResult, error) {
	body := map[string]any{"dry_run": dryRun}
	if bank != "" {
		body["bank"] = bank
	}
	var out FetchResult
	return &out, c.doWith(c.long, "POST", "/fetch", body, &out)
}

// PendingMsg is a not-yet-imported statement email waiting in the mailbox.
type PendingMsg struct {
	Bank     string `json:"bank"`
	MsgID    string `json:"msgid"`
	Subject  string `json:"subject"`
	Filename string `json:"filename"`
}
type PendingResult struct {
	Mailbox  string       `json:"mailbox"`
	Messages []PendingMsg `json:"messages"`
}

// Pending lists new statements without importing (fast — for staged progress).
func (c *Client) Pending(bank string) (*PendingResult, error) {
	var out PendingResult
	return &out, c.doWith(c.long, "GET", "/fetch/pending?bank="+url.QueryEscape(bank), nil, &out)
}

type FetchOneResult struct {
	Bank     string `json:"bank"`
	File     string `json:"file"`
	Ok       bool   `json:"ok"`
	Inserted int    `json:"inserted"`
	Already  int    `json:"already"`
	Verified bool   `json:"verified"`
	Error    string `json:"error"`
}

// FetchOne imports one statement message (by Message-ID).
func (c *Client) FetchOne(bank, msgid string) (*FetchOneResult, error) {
	var out FetchOneResult
	body := map[string]any{"bank": bank, "msgid": msgid}
	return &out, c.doWith(c.long, "POST", "/fetch/one", body, &out)
}

type SyncResult struct {
	Bank     string `json:"bank"`
	Account  string `json:"account"`
	Fetched  int    `json:"fetched"`
	Inserted int    `json:"inserted"`
	Updated  int    `json:"updated"`
}

func (c *Client) Sync(bank, account string, daysBack int) (*SyncResult, error) {
	var out SyncResult
	body := map[string]any{"bank": bank, "account": account, "days_back": daysBack}
	return &out, c.doWith(c.long, "POST", "/sync", body, &out)
}

type DateRange struct {
	Start string `json:"start"`
	End   string `json:"end"`
}

type ImportSummary struct {
	Rows                 int        `json:"rows"`
	DateRange            *DateRange `json:"date_range"`
	OpeningBalance       *float64   `json:"opening_balance"`
	ClosingBalance       *float64   `json:"closing_balance"`
	BalanceChainVerified bool       `json:"balance_chain_verified"`
}

type ImportResult struct {
	Bank     string        `json:"bank"`
	Account  string        `json:"account"`
	Profile  string        `json:"profile"`
	Format   string        `json:"format"`
	Rows     int           `json:"rows"`
	Inserted int           `json:"inserted"`
	Skipped  int           `json:"skipped_already_present"`
	DryRun   bool          `json:"dry_run"`
	Summary  ImportSummary `json:"summary"`
}

func (c *Client) Import(bank, account, path string, dryRun, ai bool, password string) (*ImportResult, error) {
	var out ImportResult
	body := map[string]any{
		"bank": bank, "account": account, "path": path,
		"dry_run": dryRun, "ai_fallback": ai,
	}
	if password != "" {
		body["password"] = password
	}
	return &out, c.doWith(c.long, "POST", "/import", body, &out)
}

// MerchantDetail returns a merchant's category breakdown and recent examples,
// or an error (e.g. "unknown merchant" when there's no history yet).
func (c *Client) MerchantDetail(key string) (*MerchantDetail, error) {
	var out MerchantDetail
	err := c.do("GET", "/merchants/"+url.PathEscape(key), nil, &out)
	return &out, err
}

func (c *Client) AddCategory(name string) error {
	return c.do("POST", "/categories", map[string]any{"category": name}, nil)
}

func (c *Client) RenameCategory(old, name string) error {
	return c.do("POST", "/categories/rename", map[string]any{"old": old, "new": name}, nil)
}
