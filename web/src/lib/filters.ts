import { writable } from 'svelte/store'

export type Range = 'month' | '3m' | '6m' | '12m'

// Shared, cross-page filter state. (URL-encoding is a later refinement.)
export const range = writable<Range>('month')
export const bank = writable<string>('all') // 'all' | a bank key
export const search = writable<string>('') // free-text, used by the Explorer

export const RANGES: { key: Range; label: string; months: number }[] = [
  { key: 'month', label: 'This month', months: 1 },
  { key: '3m', label: '3M', months: 3 },
  { key: '6m', label: '6M', months: 6 },
  { key: '12m', label: '12M', months: 12 },
]

export function monthsFor(r: Range): number {
  return RANGES.find((x) => x.key === r)?.months ?? 1
}
