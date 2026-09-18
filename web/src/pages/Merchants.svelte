<script lang="ts">
  import FilterBar from '../components/FilterBar.svelte'
  import { api, type Merchant, type MerchantDetail } from '../lib/api'
  import { search } from '../lib/filters'
  import { signed, pct, num, dayLabel } from '../lib/format'

  let loading = true
  let error = ''
  let merchants: Merchant[] = []
  let selected: string | null = null
  let detail: MerchantDetail | null = null
  let detailLoading = false

  function leaf(cat: string): string {
    const p = cat.split(':')
    return (p[p.length - 1] || cat).replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  }

  async function loadList() {
    loading = true; error = ''
    try {
      merchants = (await api.merchants()).sort((a, b) => b.samples - a.samples)
      if (!selected && merchants.length) select(merchants[0].key)
    } catch (e) {
      error = (e as Error).message
    } finally {
      loading = false
    }
  }
  async function select(key: string) {
    selected = key
    detailLoading = true
    try {
      detail = await api.merchant(key)
    } catch {
      detail = null
    } finally {
      detailLoading = false
    }
  }
  loadList()

  $: q = $search.toLowerCase()
  $: filtered = q ? merchants.filter((m) => m.merchant.toLowerCase().includes(q) || m.key.includes(q)) : merchants
</script>

<header class="head">
  <div>
    <h1>Merchants</h1>
    <p>{merchants.length} learned merchants</p>
  </div>
</header>

<FilterBar banks={[]} showRange={false} />

{#if error}
  <div class="card banner">Couldn’t load: {error}</div>
{:else}
  <div class="split">
    <div class="card list">
      {#each filtered as m}
        <button class="mrow" class:on={selected === m.key} on:click={() => select(m.key)}>
          <span class="mname">{m.merchant}{#if m.conflicted}<span class="dot" title="multiple categories">•</span>{/if}</span>
          <span class="mcat muted">{leaf(m.top_category)}</span>
          <span class="msamples num muted">{m.samples}×</span>
        </button>
      {/each}
      {#if !loading && filtered.length === 0}<p class="empty muted">No merchants match.</p>{/if}
    </div>

    <div class="card detail">
      {#if detailLoading}
        <p class="muted">loading…</p>
      {:else if detail}
        <div class="dhead">
          <h2>{detail.merchant}</h2>
          <span class="muted num">{detail.samples} transactions</span>
        </div>

        <div class="section-title">Category mix</div>
        <div class="breakdown">
          {#each detail.breakdown as b}
            <div class="brow">
              <span class="bname">{leaf(b.category)}</span>
              <div class="bbar"><div class="bfill" style={`width:${b.share * 100}%`}></div></div>
              <span class="bshare num muted">{pct(b.share * 100, 0)}</span>
              <span class="bcount num muted">{b.count}×</span>
            </div>
          {/each}
        </div>

        <div class="section-title">Recent</div>
        <table>
          <tbody>
            {#each detail.examples.slice(0, 12) as t}
              <tr>
                <td class="num muted">{dayLabel(t.date)}</td>
                <td class="muted">{leaf(t.category)}</td>
                <td class="r num" class:pos={num(t.amount) >= 0} class:neg={num(t.amount) < 0}>{signed(t.amount)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {:else}
        <p class="muted">Select a merchant.</p>
      {/if}
    </div>
  </div>
{/if}

<style>
  .head h1 { margin: 0; font-size: 20px; font-weight: 600; letter-spacing: -0.01em; }
  .head p { margin: 6px 0 0; font-size: 12px; color: var(--muted); }
  .banner { padding: 16px; color: var(--neg); }
  .split { display: grid; grid-template-columns: 340px 1fr; gap: 14px; align-items: start; }
  .list { padding: 6px; max-height: 70vh; overflow-y: auto; display: flex; flex-direction: column; }
  .mrow { display: grid; grid-template-columns: 1fr auto auto; gap: 10px; align-items: center; background: transparent; border: 0; color: var(--text); text-align: left; cursor: pointer; padding: 9px 10px; border-radius: 5px; font-size: 12px; }
  .mrow:hover { background: var(--surface-2); }
  .mrow.on { background: var(--surface-2); }
  .mrow.on .mname { color: var(--accent); }
  .mname { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .dot { color: var(--warn); margin-left: 5px; }
  .mcat { font-size: 11px; }
  .detail { padding: 18px 20px; min-height: 200px; }
  .dhead { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 16px; }
  .dhead h2 { margin: 0; font-size: 16px; font-weight: 600; }
  .section-title { font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); margin: 14px 0 8px; }
  .breakdown { display: flex; flex-direction: column; gap: 8px; }
  .brow { display: grid; grid-template-columns: 130px 1fr 44px 44px; gap: 10px; align-items: center; font-size: 12px; }
  .bname { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .bbar { height: 6px; background: var(--surface-2); border-radius: 3px; overflow: hidden; }
  .bfill { height: 100%; background: var(--accent); opacity: 0.7; }
  .bshare, .bcount { text-align: right; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  td { padding: 7px 8px; border-bottom: 1px solid var(--border); }
  tr:last-child td { border-bottom: 0; }
  .r { text-align: right; }
  .empty { padding: 16px; text-align: center; }
</style>
