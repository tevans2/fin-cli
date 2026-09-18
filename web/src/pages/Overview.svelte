<script lang="ts">
  import FilterBar from '../components/FilterBar.svelte'
  import { api, type Bank, type Status, type CashflowRow, type Txn, type VerifyRow } from '../lib/api'
  import { bank } from '../lib/filters'
  import { money, signed, spend, pct, pp, num, dayLabel } from '../lib/format'

  export let banks: Bank[] = []
  export let status: Status | null = null

  let loading = true
  let error = ''
  let cur: CashflowRow | null = null
  let prev: CashflowRow | null = null
  let cats: { label: string; amount: number; share: number }[] = []
  let catTotal = 0
  let verify: VerifyRow[] = []
  let largest: Txn[] = []
  let monthLabelStr = ''

  function leaf(cat: string): string {
    const parts = cat.split(':')
    const key = parts.length >= 2 ? parts[1] : parts[0]
    return key.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  }
  function depth2(cat: string): string {
    return cat.split(':').slice(0, 2).join(':')
  }
  function prettyAccount(a: string): string {
    return a.replace(/^assets:bank:/, '').replace(/^assets:/, '').split(':').map((s) => s.replace(/-/g, ' ')).join(' · ')
  }

  function delta(c: number, p: number) {
    const change = c - p
    const pctv = p !== 0 ? (change / Math.abs(p)) * 100 : 0
    return { change, pctv }
  }

  async function load(bk: string) {
    loading = true
    error = ''
    try {
      const now = new Date()
      const y = now.getFullYear()
      const m = String(now.getMonth() + 1).padStart(2, '0')
      const monthStart = `${y}-${m}-01`
      monthLabelStr = now.toLocaleDateString('en-ZA', { month: 'long', year: 'numeric' })

      const [flow, txns, ver] = await Promise.all([
        api.cashflow(13, bk),
        api.transactions({ since: monthStart, bank: bk, limit: 2000 }),
        api.verify().catch(() => [] as VerifyRow[]),
      ])

      const rows = [...flow].sort((a, b) => a.month.localeCompare(b.month))
      cur = rows[rows.length - 1] ?? null
      prev = rows[rows.length - 2] ?? null
      verify = ver

      // top spend categories this month, grouped at depth 2
      const byCat = new Map<string, number>()
      for (const t of txns) {
        const amt = num(t.amount)
        if (amt >= 0) continue // spend only
        byCat.set(depth2(t.category), (byCat.get(depth2(t.category)) ?? 0) + Math.abs(amt))
      }
      catTotal = [...byCat.values()].reduce((a, b) => a + b, 0)
      cats = [...byCat.entries()]
        .map(([c, amount]) => ({ label: leaf(c), amount, share: catTotal ? (amount / catTotal) * 100 : 0 }))
        .sort((a, b) => b.amount - a.amount)
        .slice(0, 7)

      largest = [...txns].sort((a, b) => Math.abs(num(b.amount)) - Math.abs(num(a.amount))).slice(0, 6)
    } catch (e) {
      error = (e as Error).message
    } finally {
      loading = false
    }
  }

  $: load($bank)

  $: incomeD = cur && prev ? delta(num(cur.income), num(prev.income)) : null
  $: spendD = cur && prev ? delta(num(cur.spend), num(prev.spend)) : null
  $: netD = cur && prev ? delta(num(cur.net), num(prev.net)) : null
  $: rateD = cur && prev ? cur.savings_rate - prev.savings_rate : null
  $: drift = verify.filter((v) => !v.ok && v.difference !== null)
</script>

<header class="head">
  <div>
    <h1>Overview</h1>
    <p>{monthLabelStr} · month to date</p>
  </div>
  <div class="verify-chip" class:bad={drift.length > 0}>
    {#if drift.length > 0}
      {drift.length} account{drift.length > 1 ? 's' : ''} drifting
    {:else}
      all reconciled
    {/if}
  </div>
</header>

<FilterBar {banks} />

{#if error}
  <div class="card banner">Couldn’t load: {error}</div>
{:else}
  <!-- KPI cards -->
  <div class="kpis">
    <div class="card kpi">
      <div class="klabel">Income</div>
      <div class="kval num">{cur ? money(cur.income) : '—'}</div>
      {#if incomeD}<div class="ksub">{sub(incomeD)}</div>{/if}
    </div>
    <div class="card kpi">
      <div class="klabel">Spend</div>
      <div class="kval num">{cur ? spend(cur.spend) : '—'}</div>
      {#if spendD}<div class="ksub">{sub(spendD, true)}</div>{/if}
    </div>
    <div class="card kpi">
      <div class="klabel">Net</div>
      <div class="kval num" class:pos={cur && num(cur.net) >= 0} class:neg={cur && num(cur.net) < 0}>{cur ? signed(cur.net) : '—'}</div>
      {#if netD}<div class="ksub">{sub(netD)}</div>{/if}
    </div>
    <div class="card kpi">
      <div class="klabel">Savings rate</div>
      <div class="kval num">{cur ? pct(cur.savings_rate) : '—'}</div>
      {#if rateD !== null}<div class="ksub muted">{pp(rateD)} vs last month</div>{/if}
    </div>
  </div>

  <div class="grid2">
    <!-- Top categories -->
    <div class="card panel">
      <div class="panel-head"><h2>Top categories</h2><span class="muted">this month</span></div>
      <div class="cats">
        {#each cats as c}
          <div class="cat">
            <span class="cat-name">{c.label}</span>
            <div class="cat-bar"><div class="cat-fill" style={`width:${c.share}%`}></div></div>
            <span class="cat-amt num neg">{spend(c.amount)}</span>
            <span class="cat-share num muted">{pct(c.share, 0)}</span>
          </div>
        {/each}
        {#if !loading && cats.length === 0}<p class="muted">No spend yet this month.</p>{/if}
      </div>
      <div class="cat-total">
        <span class="muted">{cats.length} categories</span>
        <span class="num neg">{spend(catTotal)}</span>
      </div>
    </div>

    <!-- Verify -->
    <div class="card panel">
      <div class="panel-head"><h2>Verify</h2><span class="mono muted">fin verify</span></div>
      <div class="verify">
        {#each verify as v}
          <div class="vrow">
            <span class="vacct">{prettyAccount(v.account)}</span>
            <span class="vstatus" class:ok={v.ok} class:bad={!v.ok}>{v.ok ? 'reconciled' : 'drift'}</span>
            <span class="num" class:neg={!v.ok}>{v.difference !== null ? signed(v.difference) : '—'}</span>
          </div>
        {/each}
        {#if !loading && verify.length === 0}<p class="muted">No statement balances yet.</p>{/if}
      </div>
    </div>
  </div>

  <!-- Largest this month -->
  <div class="card panel">
    <div class="panel-head"><h2>Largest this month</h2></div>
    <table>
      <thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Account</th><th class="r">Amount</th></tr></thead>
      <tbody>
        {#each largest as t}
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
    {#if !loading && largest.length === 0}<p class="muted empty">Nothing this month.</p>{/if}
  </div>

  <footer class="foot">
    <span>{status?.uncategorized ?? 0} uncategorized · {status?.needs_review ?? 0} need review</span>
    <span class="muted">Read-only — triage in the TUI (<span class="mono">fin tui</span>)</span>
  </footer>
{/if}

<script lang="ts" context="module">
  import { signed as _signed } from '../lib/format'
  // build a delta subtitle like "↑ R2 150.18 (+8.9%) vs last month"
  function sub(d: { change: number; pctv: number }, spendish = false): string {
    if (Math.abs(d.change) < 0.005) return 'unchanged vs last month'
    const arrow = d.change > 0 ? '↑' : '↓'
    const amt = _signed(Math.abs(d.change)).replace('+', '')
    const p = (d.pctv >= 0 ? '+' : '−') + Math.abs(d.pctv).toFixed(1) + '%'
    return `${arrow} ${amt} (${p}) vs last month`
  }
</script>

<style>
  .head { display: flex; align-items: flex-end; justify-content: space-between; }
  .head h1 { margin: 0; font-size: 20px; font-weight: 600; letter-spacing: -0.01em; }
  .head p { margin: 6px 0 0; font-size: 12px; color: var(--muted); }
  .verify-chip { font-size: 12px; color: var(--pos); border: 1px solid var(--border); border-radius: 999px; padding: 4px 12px; }
  .verify-chip.bad { color: var(--warn); }
  .banner { padding: 16px; color: var(--neg); }

  .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
  .kpi { padding: 16px 18px; display: flex; flex-direction: column; gap: 6px; }
  .klabel { font-size: 11px; letter-spacing: 0.04em; color: var(--muted); }
  .kval { font-size: 24px; font-weight: 600; }
  .ksub { font-size: 11px; color: var(--muted); }

  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .panel { padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }
  .panel-head { display: flex; align-items: baseline; justify-content: space-between; }
  .panel-head h2 { margin: 0; font-size: 13px; font-weight: 600; }
  .panel-head .muted { font-size: 11px; }

  .cats { display: flex; flex-direction: column; gap: 9px; }
  .cat { display: grid; grid-template-columns: 100px 1fr 92px 44px; align-items: center; gap: 10px; font-size: 12px; }
  .cat-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .cat-bar { height: 6px; background: var(--surface-2); border-radius: 3px; overflow: hidden; }
  .cat-fill { height: 100%; background: var(--accent); opacity: 0.7; }
  .cat-amt { text-align: right; }
  .cat-share { text-align: right; }
  .cat-total { display: flex; justify-content: space-between; border-top: 1px solid var(--border); padding-top: 10px; font-size: 12px; }

  .verify { display: flex; flex-direction: column; gap: 10px; }
  .vrow { display: grid; grid-template-columns: 1fr auto 92px; align-items: center; gap: 12px; font-size: 12px; }
  .vstatus.ok { color: var(--pos); }
  .vstatus.bad { color: var(--warn); }
  .vrow .num { text-align: right; }

  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { text-align: left; font-weight: 500; color: var(--muted); padding: 6px 8px; border-bottom: 1px solid var(--border); font-size: 11px; }
  td { padding: 8px; border-bottom: 1px solid var(--border); }
  tr:last-child td { border-bottom: 0; }
  .r { text-align: right; }
  .empty { padding: 16px; text-align: center; }

  .foot { display: flex; justify-content: space-between; font-size: 12px; padding-top: 4px; }
</style>
