<script lang="ts">
  import { onMount } from 'svelte'
  import Nav from './components/Nav.svelte'
  import Overview from './pages/Overview.svelte'
  import Cashflow from './pages/Cashflow.svelte'
  import Trends from './pages/Trends.svelte'
  import Recurring from './pages/Recurring.svelte'
  import Explorer from './pages/Explorer.svelte'
  import Merchants from './pages/Merchants.svelte'
  import ShortcutHelp from './components/ShortcutHelp.svelte'
  import { route, installKeys } from './lib/router'
  import { api, type Status, type Bank } from './lib/api'

  let status: Status | null = null
  let banks: Bank[] = []
  let showHelp = false

  onMount(() => {
    installKeys(() => (showHelp = !showHelp))
    api.status().then((s) => (status = s)).catch(() => {})
    api.banks().then((b) => (banks = b)).catch(() => {})
  })
</script>

<div class="app">
  <Nav {status} />
  <main>
    {#if $route === 'overview'}
      <Overview {banks} {status} />
    {:else if $route === 'cashflow'}
      <Cashflow {banks} />
    {:else if $route === 'trends'}
      <Trends {banks} />
    {:else if $route === 'recurring'}
      <Recurring {banks} />
    {:else if $route === 'explorer'}
      <Explorer {banks} />
    {:else if $route === 'merchants'}
      <Merchants />
    {/if}
  </main>
</div>

{#if showHelp}
  <ShortcutHelp on:close={() => (showHelp = false)} />
{/if}

<style>
  .app { display: flex; min-height: 100vh; }
  main { flex-grow: 1; padding: 28px 32px; display: flex; flex-direction: column; gap: 18px; max-width: 1280px; }
</style>
