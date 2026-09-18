<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import * as echarts from 'echarts'

  export let option: echarts.EChartsOption
  export let height = '260px'

  let el: HTMLDivElement
  let chart: echarts.ECharts | null = null

  function resize() { chart?.resize() }

  onMount(() => {
    chart = echarts.init(el, undefined, { renderer: 'canvas' })
    chart.setOption(option)
    window.addEventListener('resize', resize)
  })
  onDestroy(() => {
    window.removeEventListener('resize', resize)
    chart?.dispose()
  })

  $: if (chart && option) chart.setOption(option, true)
</script>

<div class="chart" bind:this={el} style={`height:${height}`}></div>

<style>
  .chart { width: 100%; }
</style>
