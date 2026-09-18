<script lang="ts">
  import { range, bank, search, RANGES } from '../lib/filters'
  import type { Bank } from '../lib/api'

  export let banks: Bank[] = []
  export let txnCount: number | null = null
  export let showRange = true
</script>

<div class="bar">
  {#if showRange}
    <div class="chips">
      {#each RANGES as r}
        <button class="chip" class:on={$range === r.key} on:click={() => range.set(r.key)}>{r.label}</button>
      {/each}
      <button class="chip" disabled title="coming soon">Custom</button>
    </div>
  {/if}

  <div class="grow"></div>

  <label class="field">
    <span class="flabel">Bank</span>
    <select bind:value={$bank}>
      <option value="all">All banks{banks.length ? ` (${banks.length})` : ''}</option>
      {#each banks as b}
        <option value={b.bank}>{b.name}</option>
      {/each}
    </select>
  </label>

  <input class="search" type="search" placeholder="Search transactions" bind:value={$search} />

  {#if txnCount !== null}
    <span class="count num">{txnCount.toLocaleString('en-ZA')} txns</span>
  {/if}
</div>

<style>
  .bar {
    display: flex; align-items: center; gap: 12px;
    padding: 12px 0; border-bottom: 1px solid var(--border);
  }
  .chips { display: flex; gap: 4px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 3px; }
  .chip {
    border: 0; background: transparent; color: var(--muted); cursor: pointer;
    font-size: 12px; padding: 5px 10px; border-radius: 4px;
  }
  .chip:hover:not(:disabled) { color: var(--text); }
  .chip.on { background: var(--surface-2); color: var(--accent); }
  .chip:disabled { opacity: 0.4; cursor: default; }
  .grow { flex-grow: 1; }
  .field { display: flex; align-items: center; gap: 8px; }
  .flabel { font-size: 11px; color: var(--muted); }
  select, .search {
    background: var(--surface); border: 1px solid var(--border); color: var(--text);
    border-radius: 6px; padding: 6px 10px; font-size: 12px; outline: none;
  }
  select:focus, .search:focus { border-color: var(--select); }
  .search { width: 180px; }
  .count { font-size: 12px; color: var(--muted); }
</style>
