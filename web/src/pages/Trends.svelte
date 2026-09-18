<script lang="ts">
  import FilterBar from '../components/FilterBar.svelte'
  import { api, type Bank, type Trend } from '../lib/api'
  import { bank } from '../lib/filters'
  import { money, pct, num } from '../lib/format'

  export let banks: Bank[] = []

  let loading = true
  let error = ''
  let trends: Trend[] = []
  let columns: string[] = []
  let months = 6
  let depth = 2

  const MONTHS = [3, 6, 12]
  const DEPTHS = [1, 2, 3]

  function leaf(cat: string): string {
    const parts = cat.split(':')
    const key = parts[parts.length - 1] || cat
    return key.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  }

  async function load(bk: string, m: number, d: number) {
    loading = true; error = ''
    try {
      const resp = await api.trends(m, d, bk)
      columns = resp.columns
      trends = [...resp.trends].sort((a, b) => b.change_pct - a.change_pct)
    } catch (e) {
      error = (e as Error).message
    } finally {
      loading = false
    }
  }
  $: load($bank, months, depth)

  $: maxAbs = Math.max(1, ...trends.map((t) => Math.abs(t.change_pct)))
</script>

<header class="head">
  <div>
    <h1>Trends</h1>
    <p>category spend vs its {months}-month trailing average{columns.length ? ` · latest ${columns[columns.length - 1]}` : ''}</p>
  </div>
</header>

<FilterBar {banks} showRange={false} />

<div class="controls">
  <div class="seg">
    <span class="seg-label">Window</span>
    {#each MONTHS as m}<button class="chip" class:on={months === m} on:click={() => (months = m)}>{m}M</button>{/each}
  </div>
  <div class="seg">
    <span class="seg-label">Depth</span>
    {#each DEPTHS as d}<button class="chip" class:on={depth === d} on:click={() => (depth = d)}>{d}</button>{/each}
  </div>
</div>

{#if error}
  <div class="card banner">Couldn’t load: {error}</div>
{:else}
  <div class="card panel">
    <table>
      <thead><tr><th>Category</th><th class="r">This month</th><th class="r">Trailing avg</th><th>Change</th></tr></thead>
      <tbody>
        {#each trends as t}
          {@const up = t.change_pct > 0}
          <tr>
            <td>{leaf(t.category)}</td>
            <td class="r num">{money(t.latest)}</td>
            <td class="r num muted">{money(t.previous_avg)}</td>
            <td>
              <div class="change">
                <span class="delta num" class:neg={up} class:pos={!up}>{up ? '↑' : '↓'} {pct(Math.abs(t.change_pct) * 100, 0)}</span>
                <div class="cbar"><div class="cfill" class:neg={up} class:pos={!up} style={`width:${(Math.abs(t.change_pct) / maxAbs) * 100}%`}></div></div>
              </div>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    {#if !loading && trends.length === 0}<p class="empty muted">No category movement in this window.</p>{/if}
  </div>
  <p class="note muted">↑ spending more than the trailing average · ↓ spending less</p>
{/if}

<style>
  .head h1 { margin: 0; font-size: 20px; font-weight: 600; letter-spacing: -0.01em; }
  .head p { margin: 6px 0 0; font-size: 12px; color: var(--muted); }
  .controls { display: flex; gap: 18px; }
  .seg { display: flex; align-items: center; gap: 6px; }
  .seg-label { font-size: 11px; color: var(--muted); }
  .chip { border: 1px solid var(--border); background: var(--surface); color: var(--muted); cursor: pointer; font-size: 12px; padding: 4px 10px; border-radius: 5px; }
  .chip:hover { color: var(--text); }
  .chip.on { background: var(--surface-2); color: var(--accent); border-color: var(--select); }
  .banner { padding: 16px; color: var(--neg); }
  .panel { padding: 16px 18px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { text-align: left; font-weight: 500; color: var(--muted); padding: 7px 8px; border-bottom: 1px solid var(--border); font-size: 11px; }
  td { padding: 8px; border-bottom: 1px solid var(--border); vertical-align: middle; }
  tr:last-child td { border-bottom: 0; }
  .r { text-align: right; }
  .change { display: flex; align-items: center; gap: 10px; }
  .delta { width: 74px; }
  .cbar { flex-grow: 1; height: 6px; background: var(--surface-2); border-radius: 3px; overflow: hidden; max-width: 220px; }
  .cfill { height: 100%; }
  .cfill.neg { background: var(--neg); opacity: 0.7; }
  .cfill.pos { background: var(--pos); opacity: 0.7; }
  .empty { padding: 20px; text-align: center; }
  .note { font-size: 11px; margin: 4px 0 0; }
</style>
