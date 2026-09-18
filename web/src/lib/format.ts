// Money arrives from the API as decimal strings. Parse to number only for
// layout/formatting — never round-trip a displayed value back into a write.

export function num(v: string | number | null | undefined): number {
  if (v === null || v === undefined || v === '') return 0
  const n = typeof v === 'number' ? v : parseFloat(v)
  return Number.isFinite(n) ? n : 0
}

const zar = new Intl.NumberFormat('en-ZA', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

// R12 345.67 (magnitude only)
export function money(v: string | number): string {
  return 'R' + zar.format(Math.abs(num(v)))
}

// Signed, e.g. +R22 159.82 / −R2 150.18 (uses a real minus sign)
export function signed(v: string | number): string {
  const n = num(v)
  const sign = n < 0 ? '−' : '+'
  return sign + 'R' + zar.format(Math.abs(n))
}

// A spend line: shown negative (−R…) since expenses are stored negative.
export function spend(v: string | number): string {
  return '−R' + zar.format(Math.abs(num(v)))
}

// Compact for chart axes: R48k, R1.2m
export function compact(v: string | number): string {
  const n = Math.abs(num(v))
  if (n >= 1_000_000) return 'R' + (n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1) + 'm'
  if (n >= 1_000) return 'R' + Math.round(n / 1_000) + 'k'
  return 'R' + Math.round(n)
}

export function pct(v: number | string | null | undefined, digits = 1): string {
  return num(v).toFixed(digits) + '%'
}

// change in percentage points
export function pp(delta: number, digits = 1): string {
  const sign = delta < 0 ? '−' : '+'
  return sign + Math.abs(delta).toFixed(digits) + ' pp'
}

// "2026-09" -> "Sep 2026"
export function monthLabel(m: string): string {
  const [y, mo] = m.split('-')
  const names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${names[parseInt(mo, 10)] || mo} ${y}`
}

// "2026-09-15" -> "15 Sep"
export function dayLabel(d: string): string {
  const [, mo, day] = d.split('-')
  const names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${day} ${names[parseInt(mo, 10)] || mo}`
}

// group separators for a bare number (table cells): 48 500.00
export function grouped(v: string | number): string {
  return zar.format(Math.abs(num(v)))
}
