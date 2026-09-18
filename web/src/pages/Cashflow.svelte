<script lang="ts">
  import FilterBar from '../components/FilterBar.svelte'
  import Chart from '../components/Chart.svelte'
  import { api, type Bank, type CashflowRow } from '../lib/api'
  import { bank } from '../lib/filters'
  import { money, signed, grouped, pct, num, monthLabel, compact } from '../lib/format'

  export let banks: Bank[] = []

  let loading = true
  let error = ''
  let rows: CashflowRow[] = []

  async function load(bk: string) {
    loading = true; error = ''
    try {
      const flow = await api.cashflow(12, bk)
      rows = [...flow].sort((a, b) => a.month.localeCompare(b.month))
    } catch (e) {
      error = (e as Error).message
    } finally {
      loading = false
    }
  }
  $: load($bank)

  $: sumIncome = rows.reduce((a, r) => a + num(r.income), 0)
  $: sumSpend = rows.reduce((a, r) => a + num(r.spend), 0)
  $: sumNet = rows.reduce((a, r) => a + num(r.net), 0)
  $: months = rows.length || 1
  $: posMonths = rows.filter((r) => num(r.net) > 0).length
  $: overallRate = sumIncome ? (sumNet / sumIncome) * 100 : 0
  $: best = rows.reduce<CashflowRow | null>((b, r) => (!b || r.savings_rate > b.savings_rate ? r : b), null)
  $: worst = rows.reduce<CashflowRow | null>((w, r) => (!w || r.savings_rate < w.savings_rate ? r : w), null)
  $: maxNet = Math.max(1, ...rows.map((r) => Math.abs(num(r.net))))

  $: option = {
    grid: { left: 52, right: 46, top: 24, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1d2127', borderColor: '#262b32', textStyle: { color: '#e6e9ef', fontSize: 12 },
      valueFormatter: (v: number) => (typeof v === 'number' && v <= 100 && v >= 0 ? v.toFixed(1) + '%' : money(v)),
    },
    legend: {
      data: ['income', 'spend', 'savings rate'], right: 0, top: 0,
      textStyle: { color: '#8a92a0', fontSize: 11 }, itemWidth: 10, itemHeight: 10, icon: 'roundRect',
    },
    xAxis: {
      type: 'category', data: rows.map((r) => monthLabel(r.month)),
      axisLine: { lineStyle: { color: '#262b32' } }, axisTick: { show: false },
      axisLabel: { color: '#8a92a0', fontSize: 10 },
    },
    yAxis: [
      { type: 'value', axisLabel: { color: '#565d68', fontSize: 10, formatter: (v: number) => compact(v) },
        splitLine: { lineStyle: { color: '#1a1e24' } }, axisLine: { show: false } },
      { type: 'value', axisLabel: { color: '#565d68', fontSize: 10, formatter: (v: number) => v + '%' },
        splitLine: { show: false }, axisLine: { show: false }, max: 100 },
    ],
    series: [
      { name: 'income', type: 'bar', data: rows.map((r) => num(r.income)), itemStyle: { color: '#87ff87', opacity: 0.85, borderRadius: [2, 2, 0, 0] }, barMaxWidth: 16 },
      { name: 'spend', type: 'bar', data: rows.map((r) => num(r.spend)), itemStyle: { color: '#ff5f5f', opacity: 0.85, borderRadius: [2, 2, 0, 0] }, barMaxWidth: 16 },
      { name: 'savings rate', type: 'line', yAxisIndex: 1, data: rows.map((r) => +r.savings_rate.toFixed(1)), smooth: true, symbol: 'circle', symbolSize: 5, lineStyle: { color: '#5fd7ff', width: 2 }, itemStyle: { color: '#5fd7ff' } },
    ],
  } as any

  function exportCsv() {
    const head = ['month', 'income', 'spend', 'net', 'savings_rate']
    const lines = [head.join(',')]
    for (const r of rows) lines.push([r.month, r.income, r.spend, r.net, r.savings_rate].join(','))
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'cashflow.csv'
    a.click()
    URL.revokeObjectURL(a.href)
  }
</script>

<header class="head">
  <div>
    <h1>Cashflow</h1>
    <p>{rows.length ? `${monthLabel(rows[0].month)} – ${monthLabel(rows[rows.length - 1].month)} · ${rows.length} months` : 'last 12 months'}</p>
  </div>
</header>

<FilterBar {banks} showRange={false} />

{#if error}
  <div class="card banner">Couldn’t load: {error}</div>
{:else}
  <div class="kpis">
    <div class="card kpi">
      <div class="klabel">Income · {months} mo</div>
      <div class="kval num">{money(sumIncome)}</div>
      <div class="ksub muted">{money(sumIncome / months)} / month avg</div>
    </div>
    <div class="card kpi">
      <div class="klabel">Spend · {months} mo</div>
      <div class="kval num">{money(sumSpend)}</div>
      <div class="ksub muted">{money(sumSpend / months)} / month avg</div>
    </div>
    <div class="card kpi">
      <div class="klabel">Net · {months} mo</div>
      <div class="kval num" class:pos={sumNet >= 0} class:neg={sumNet < 0}>{signed(sumNet)}</div>
      <div class="ksub muted">positive in {posMonths} of {months} months</div>
    </div>
    <div class="card kpi">
      <div class="klabel">Savings rate</div>
      <div class="kval num">{pct(overallRate)}</div>
      {#if best && worst}<div class="ksub muted">best {monthLabel(best.month).slice(0, 3)} {pct(best.savings_rate)} · worst {monthLabel(worst.month).slice(0, 3)} {pct(worst.savings_rate)}</div>{/if}
    </div>
  </div>

  <div class="card panel">
    <div class="panel-head"><h2>Income vs spend</h2></div>
    <Chart {option} height="300px" />
  </div>

  <div class="card panel">
    <div class="panel-head"><h2>Month by month</h2><button class="btn" on:click={exportCsv}>Export CSV</button></div>
    <table>
      <thead><tr><th>Month</th><th class="r">Income</th><th class="r">Spend</th><th class="r">Net</th><th class="r">Rate</th><th>Net, relative</th></tr></thead>
      <tbody>
        {#each rows as r}
          <tr>
            <td>{monthLabel(r.month)}</td>
            <td class="r num">{grouped(r.income)}</td>
            <td class="r num">{grouped(r.spend)}</td>
            <td class="r num" class:pos={num(r.net) >= 0} class:neg={num(r.net) < 0}>{signed(r.net)}</td>
            <td class="r num muted">{pct(r.savings_rate)}</td>
            <td>
              <div class="relbar"><div class="relfill" style={`width:${(Math.abs(num(r.net)) / maxNet) * 100}%`} class:pos={num(r.net) >= 0} class:neg={num(r.net) < 0}></div></div>
            </td>
          </tr>
        {/each}
      </tbody>
      <tfoot>
        <tr>
          <td>Total</td>
          <td class="r num">{grouped(sumIncome)}</td>
          <td class="r num">{grouped(sumSpend)}</td>
          <td class="r num" class:pos={sumNet >= 0}>{signed(sumNet)}</td>
          <td class="r num muted">{pct(overallRate)}</td>
          <td></td>
        </tr>
      </tfoot>
    </table>
    <p class="note muted">amounts in ZAR</p>
  </div>
{/if}

<style>
  .head h1 { margin: 0; font-size: 20px; font-weight: 600; letter-spacing: -0.01em; }
  .head p { margin: 6px 0 0; font-size: 12px; color: var(--muted); }
  .banner { padding: 16px; color: var(--neg); }
  .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
  .kpi { padding: 16px 18px; display: flex; flex-direction: column; gap: 6px; }
  .klabel { font-size: 11px; color: var(--muted); }
  .kval { font-size: 22px; font-weight: 600; }
  .ksub { font-size: 11px; }
  .panel { padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }
  .panel-head { display: flex; align-items: center; justify-content: space-between; }
  .panel-head h2 { margin: 0; font-size: 13px; font-weight: 600; }
  .btn { background: var(--surface-2); border: 1px solid var(--border); color: var(--text); border-radius: 5px; padding: 5px 10px; font-size: 11px; cursor: pointer; }
  .btn:hover { border-color: var(--select); }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { text-align: left; font-weight: 500; color: var(--muted); padding: 6px 8px; border-bottom: 1px solid var(--border); font-size: 11px; }
  td { padding: 7px 8px; border-bottom: 1px solid var(--border); }
  tfoot td { border-top: 1px solid var(--border); border-bottom: 0; font-weight: 600; }
  .r { text-align: right; }
  .relbar { height: 6px; background: var(--surface-2); border-radius: 3px; overflow: hidden; min-width: 80px; }
  .relfill { height: 100%; }
  .relfill.pos { background: var(--pos); opacity: 0.7; }
  .relfill.neg { background: var(--neg); opacity: 0.7; }
  .note { margin: 4px 0 0; font-size: 11px; }
</style>
