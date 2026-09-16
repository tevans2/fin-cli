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
	Recommended *string     `json:"recommended"`
	Confidence  float64     `json:"confidence"`
	Source      string      `json:"source"`
	Auto        bool        `json:"auto"`
	Candidates  []Candidate `json:"candidates"`
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

func (c *Client) ApplyCategory(bank, id, category string) error {
	return c.do("POST", "/categorize/apply", map[string]any{"bank": bank, "id": id, "category": category}, nil)
}

func (c *Client) Confirm(bank string, ids []string) error {
	return c.do("POST", "/categorize/confirm", map[string]any{"bank": bank, "ids": ids}, nil)
}

func (c *Client) Reject(bank, id string) error {
	return c.do("POST", "/categorize/reject", map[string]any{"bank": bank, "id": id}, nil)
}
