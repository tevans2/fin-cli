<script lang="ts">
  import FilterBar from '../components/FilterBar.svelte'
  import { api, type Bank, type Recurring } from '../lib/api'
  import { bank } from '../lib/filters'
  import { money, num } from '../lib/format'

  export let banks: Bank[] = []

  let loading = true
  let error = ''
  let items: (Recurring & { annual: number })[] = []

  function annualized(r: Recurring): number {
    const amt = Math.abs(num(r.typical_amount))
    return r.interval_days > 0 ? amt * (365 / r.interval_days) : amt
  }
  function longDate(d: string): string {
    const [y, mo, day] = d.split('-')
    const names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    return `${day} ${names[parseInt(mo, 10)] || mo} ${y}`
  }

  async function load(bk: string) {
    loading = true; error = ''
    try {
      const rows = await api.recurring(bk)
      items = rows.map((r) => ({ ...r, annual: annualized(r) })).sort((a, b) => b.annual - a.annual)
    } catch (e) {
      error = (e as Error).message
    } finally {
      loading = false
    }
  }
  $: load($bank)

  $: active = items.filter((r) => r.active)
  $: lapsed = items.filter((r) => !r.active)
  $: annualActive = active.reduce((a, r) => a + r.annual, 0)
</script>

<header class="head">
  <div>
    <h1>Recurring</h1>
    <p>subscriptions & repeating merchants</p>
  </div>
</header>

<FilterBar {banks} showRange={false} />

{#if error}
  <div class="card banner">Couldn’t load: {error}</div>
{:else}
  <div class="kpis">
    <div class="card kpi"><div class="klabel">Active</div><div class="kval num">{active.length}</div><div class="ksub muted">recurring merchants</div></div>
    <div class="card kpi"><div class="klabel">Annualized</div><div class="kval num">{money(annualActive)}</div><div class="ksub muted">estimated / year (active)</div></div>
    <div class="card kpi"><div class="klabel">Lapsed</div><div class="kval num">{lapsed.length}</div><div class="ksub muted">no recent charge</div></div>
  </div>

  <div class="card panel">
    <table>
      <thead><tr><th>Merchant</th><th>Cadence</th><th class="r">Typical</th><th class="r">Annualized</th><th>Last</th><th class="r">Seen</th><th>Status</th></tr></thead>
      <tbody>
        {#each items as r}
          <tr class:dim={!r.active}>
            <td>{r.merchant}</td>
            <td class="muted">{r.cadence}{r.interval_days ? ` · ~${r.interval_days}d` : ''}</td>
            <td class="r num">{money(r.typical_amount)}{#if !r.amount_stable}<span class="flag" title="amount varies">~</span>{/if}</td>
            <td class="r num">{money(r.annual)}</td>
            <td class="muted">{longDate(r.last)}</td>
            <td class="r num muted">{r.occurrences}×</td>
            <td>
              {#if r.active}<span class="badge ok">active</span>{:else}<span class="badge warn">lapsed</span>{/if}
              {#if !r.amount_stable}<span class="badge dimb">price varies</span>{/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    {#if !loading && items.length === 0}<p class="empty muted">No recurring merchants detected yet.</p>{/if}
  </div>
{/if}

<style>
  .head h1 { margin: 0; font-size: 20px; font-weight: 600; letter-spacing: -0.01em; }
  .head p { margin: 6px 0 0; font-size: 12px; color: var(--muted); }
  .banner { padding: 16px; color: var(--neg); }
  .kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
  .kpi { padding: 16px 18px; display: flex; flex-direction: column; gap: 6px; }
  .klabel { font-size: 11px; color: var(--muted); }
  .kval { font-size: 22px; font-weight: 600; }
  .ksub { font-size: 11px; }
  .panel { padding: 16px 18px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { text-align: left; font-weight: 500; color: var(--muted); padding: 7px 8px; border-bottom: 1px solid var(--border); font-size: 11px; }
  td { padding: 8px; border-bottom: 1px solid var(--border); }
  tr:last-child td { border-bottom: 0; }
  tr.dim td { opacity: 0.55; }
  .r { text-align: right; }
  .flag { color: var(--warn); margin-left: 3px; }
  .badge { font-size: 10px; padding: 2px 7px; border-radius: 999px; border: 1px solid var(--border); margin-right: 5px; }
  .badge.ok { color: var(--pos); }
  .badge.warn { color: var(--warn); }
  .badge.dimb { color: var(--muted); }
  .empty { padding: 20px; text-align: center; }
</style>
