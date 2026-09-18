<script lang="ts">
  import { onDestroy } from 'svelte'
  import FilterBar from '../components/FilterBar.svelte'
  import { api, type Bank, type Txn } from '../lib/api'
  import { bank, range, search, monthsFor, type Range } from '../lib/filters'
  import { signed, num, dayLabel } from '../lib/format'

  export let banks: Bank[] = []

  let loading = true
  let error = ''
  let txns: Txn[] = []
  const LIMIT = 400

  function leaf(cat: string): string {
    const p = cat.split(':')
    return (p[p.length - 1] || cat).replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  }
  function sinceFor(r: Range): string {
    const now = new Date()
    if (r === 'month') return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`
    const d = new Date(now)
    d.setMonth(d.getMonth() - monthsFor(r))
    return d.toISOString().slice(0, 10)
  }

  async function load(bk: string, r: Range, q: string) {
    loading = true; error = ''
    try {
      txns = await api.transactions({ scope: 'all', bank: bk, since: sinceFor(r), q: q || undefined, limit: LIMIT })
    } catch (e) {
      error = (e as Error).message
    } finally {
      loading = false
    }
  }

  // debounce so typing in the search box doesn't spam the API
  let timer: ReturnType<typeof setTimeout>
  function schedule(bk: string, r: Range, q: string) {
    clearTimeout(timer)
    timer = setTimeout(() => load(bk, r, q), 220)
  }
  $: schedule($bank, $range, $search)
  onDestroy(() => clearTimeout(timer))
</script>

<header class="head">
  <div>
    <h1>Explorer</h1>
    <p>{loading ? 'loading…' : `${txns.length}${txns.length >= LIMIT ? '+' : ''} transactions`}{$search ? ` · “${$search}”` : ''}</p>
  </div>
</header>

<FilterBar {banks} txnCount={loading ? null : txns.length} />

{#if error}
  <div class="card banner">Couldn’t load: {error}</div>
{:else}
  <div class="card panel">
    <table>
      <thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Account</th><th class="r">Amount</th></tr></thead>
      <tbody>
        {#each txns as t}
          <tr>
            <td class="num muted">{dayLabel(t.date)}</td>
            <td>{t.merchant || t.description}</td>
            <td class="muted">{leaf(t.category)}</td>
            <td class="muted">{t.institution}</td>
            <td class="r num" class:pos={num(t.amount) >= 0} class:neg={num(t.amount) < 0}>{signed(t.amount)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    {#if !loading && txns.length === 0}<p class="empty muted">No matching transactions.</p>{/if}
    {#if txns.length >= LIMIT}<p class="note muted">Showing the first {LIMIT} — narrow with search or a bank filter.</p>{/if}
  </div>
{/if}

<style>
  .head h1 { margin: 0; font-size: 20px; font-weight: 600; letter-spacing: -0.01em; }
  .head p { margin: 6px 0 0; font-size: 12px; color: var(--muted); }
  .banner { padding: 16px; color: var(--neg); }
  .panel { padding: 16px 18px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { text-align: left; font-weight: 500; color: var(--muted); padding: 7px 8px; border-bottom: 1px solid var(--border); font-size: 11px; position: sticky; top: 0; background: var(--surface); }
  td { padding: 8px; border-bottom: 1px solid var(--border); }
  tr:last-child td { border-bottom: 0; }
  .r { text-align: right; }
  .empty { padding: 20px; text-align: center; }
  .note { font-size: 11px; margin: 10px 0 0; }
</style>
