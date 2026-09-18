// Thin typed client for the local fin API. Same-origin: in prod the API serves
// this app and injects window.__FIN.token; in dev the Vite proxy adds the token.

const base = (typeof window !== 'undefined' && window.__FIN?.base) || ''
const token = (typeof window !== 'undefined' && window.__FIN?.token) || ''

async function get<T>(path: string): Promise<T> {
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(base + path, { headers })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = j.detail || j.error || detail
    } catch { /* ignore */ }
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json() as Promise<T>
}

// ── types (mirror the API JSON; money is decimal strings) ────────────────────

export interface Status {
  uncategorized: number
  needs_review: number
  banks?: Record<string, { uncategorized: number; needs_review: number }>
}

export interface CashflowRow {
  month: string
  income: string
  spend: string
  net: string
  savings_rate: number | null
}

export interface Trend {
  category: string
  latest: string
  previous_avg: string
  change: string
  change_pct: number
}
export interface TrendsResp { columns: string[]; trends: Trend[] }

export interface Recurring {
  merchant: string
  cadence: string
  interval_days: number
  typical_amount: string
  amount_stable: boolean
  occurrences: number
  last: string
  active: boolean
}

export interface Txn {
  id: string
  institution: string
  date: string
  amount: string
  currency: string
  description: string
  category: string
  merchant: string | null
  reviewed: boolean
  category_source: string
}

export interface Merchant {
  key: string
  merchant: string
  top_category: string
  confidence: number
  samples: number
  conflicted: boolean
}

export interface VerifyRow {
  account: string
  as_of?: string | null
  statement_balance: string
  ledger_balance: string | null
  difference: string | null
  ok: boolean
}

export interface Bank {
  bank: string
  name: string
  currency: string
  source: string
  accounts: string[]
}

// ── calls ────────────────────────────────────────────────────────────────────

export const api = {
  status: () => get<Status>('/status'),
  cashflow: (months?: number, bank?: string) =>
    get<CashflowRow[]>(`/analysis/cashflow${qs({ months, bank })}`),
  trends: (months = 6, depth = 2, bank?: string) =>
    get<TrendsResp>(`/analysis/trends${qs({ months, depth, bank })}`),
  recurring: (bank?: string) => get<Recurring[]>(`/analysis/recurring${qs({ bank })}`),
  transactions: (params: Record<string, string | number | undefined>) =>
    get<Txn[]>(`/transactions${qs(params)}`),
  merchants: () => get<Merchant[]>('/merchants'),
  verify: () => get<VerifyRow[]>('/verify'),
  banks: () => get<Bank[]>('/banks'),
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const parts: string[] = []
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '' && v !== 'all') {
      parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    }
  }
  return parts.length ? '?' + parts.join('&') : ''
}
