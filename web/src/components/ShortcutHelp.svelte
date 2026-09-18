<script lang="ts">
  import { createEventDispatcher, onMount, onDestroy } from 'svelte'
  const dispatch = createEventDispatcher()

  const rows = [
    ['go', 'Overview'], ['gc', 'Cashflow'], ['gt', 'Trends'],
    ['gr', 'Recurring'], ['gx', 'Explorer'], ['gm', 'Merchants'],
    ['/', 'Focus search'], ['?', 'Toggle this help'],
  ]

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape' || e.key === '?') dispatch('close')
  }
  onMount(() => window.addEventListener('keydown', onKey))
  onDestroy(() => window.removeEventListener('keydown', onKey))
</script>

<div class="wrap">
  <button class="scrim" aria-label="Close" on:click={() => dispatch('close')}></button>
  <div class="sheet card" role="dialog" aria-modal="true">
    <h2>Shortcuts</h2>
    <div class="grid">
      {#each rows as [k, label]}
        <kbd>{k}</kbd><span>{label}</span>
      {/each}
    </div>
    <p class="hint">The web app is read-only — triage in the TUI (<span class="mono">fin tui</span>).</p>
  </div>
</div>

<style>
  .wrap { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; z-index: 100; }
  .scrim { position: fixed; inset: 0; background: rgba(0,0,0,0.55); border: 0; padding: 0; cursor: default; }
  .sheet { position: relative; width: 360px; padding: 22px 24px; }
  h2 { margin: 0 0 16px; font-size: 15px; font-weight: 600; }
  .grid { display: grid; grid-template-columns: 44px 1fr; gap: 10px 14px; align-items: center; font-size: 13px; }
  .hint { margin: 18px 0 0; font-size: 12px; color: var(--muted); }
</style>
