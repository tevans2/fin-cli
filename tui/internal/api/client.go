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
}

func New() *Client {
	base := os.Getenv("FIN_API_URL")
	if base == "" {
		base = "http://127.0.0.1:8765"
	}
	return &Client{base: base, token: os.Getenv("FIN_API_TOKEN"), http: &http.Client{Timeout: 20 * time.Second}}
}

func (c *Client) do(method, path string, body any, out any) error {
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
	resp, err := c.http.Do(req)
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
