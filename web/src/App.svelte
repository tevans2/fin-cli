<script lang="ts">
  import { onMount } from 'svelte'
  import Nav from './components/Nav.svelte'
  import Overview from './pages/Overview.svelte'
  import Cashflow from './pages/Cashflow.svelte'
  import Placeholder from './pages/Placeholder.svelte'
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
      <Placeholder title="Trends" />
    {:else if $route === 'recurring'}
      <Placeholder title="Recurring" />
    {:else if $route === 'explorer'}
      <Placeholder title="Explorer" />
    {:else if $route === 'merchants'}
      <Placeholder title="Merchants" />
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
