<script lang="ts">
  import { route, go, type Route } from '../lib/router'
  import type { Status } from '../lib/api'

  export let status: Status | null = null

  // [route, label, kbd, svg-path(s)]
  const items: { r: Route; label: string; kbd: string; d: string }[] = [
    { r: 'overview', label: 'Overview', kbd: 'go', d: 'M2 8l6-5 6 5M4 7v6h8V7' },
    { r: 'cashflow', label: 'Cashflow', kbd: 'gc', d: 'M2 13h12M4 11V6M7 11V3M10 11V7M13 11V4' },
    { r: 'trends', label: 'Trends', kbd: 'gt', d: 'M2 11l4-4 3 3 5-6' },
    { r: 'recurring', label: 'Recurring', kbd: 'gr', d: 'M13 6a5 5 0 10-1 5M13 3v3h-3' },
    { r: 'explorer', label: 'Explorer', kbd: 'gx', d: 'M7 12A5 5 0 107 2a5 5 0 000 10zM11 11l3 3' },
    { r: 'merchants', label: 'Merchants', kbd: 'gm', d: 'M3 6l1-3h8l1 3M3 6v7h10V6M3 6h10' },
  ]
</script>

<nav>
  <div class="brand">
    <span class="logo">fin</span>
    <span class="tag">web</span>
  </div>

  <div class="items">
    {#each items as it}
      <a
        href={`#/${it.r === 'overview' ? '' : it.r}`}
        class="item"
        class:active={$route === it.r}
        on:click|preventDefault={() => go(it.r)}
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
          <path d={it.d} />
        </svg>
        <span class="label">{it.label}</span>
        <kbd>{it.kbd}</kbd>
      </a>
    {/each}
  </div>

  <div class="spacer"></div>

  <div class="inbox">
    <div class="inbox-title">Inbox</div>
    <div class="row">
      <span>Uncategorized</span>
      <span class="num" class:warn={(status?.uncategorized ?? 0) > 0}>{status?.uncategorized ?? '—'}</span>
    </div>
    <div class="row">
      <span>Needs review</span>
      <span class="num" class:warn={(status?.needs_review ?? 0) > 0}>{status?.needs_review ?? '—'}</span>
    </div>
  </div>

  <div class="shortcuts"><kbd>?</kbd><span>shortcuts</span></div>
</nav>

<style>
  nav {
    width: 224px;
    flex-shrink: 0;
    background: var(--surface);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    padding: 22px 0 18px 0;
    height: 100vh;
    position: sticky;
    top: 0;
  }
  .brand { padding: 0 20px 20px; display: flex; align-items: baseline; gap: 8px; }
  .logo { font-family: var(--font-mono); font-size: 18px; font-weight: 600; letter-spacing: -0.02em; color: var(--accent); }
  .tag { font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); }
  .items { display: flex; flex-direction: column; gap: 2px; padding: 0 12px; }
  .item {
    display: flex; align-items: center; gap: 10px; min-height: 40px;
    padding: 0 12px; border-radius: 5px; font-size: 13px; color: var(--text);
  }
  .item:hover { background: var(--surface-2); }
  .item .label { flex-grow: 1; }
  .item svg { color: var(--muted); }
  .item.active { background: var(--surface-2); color: var(--accent); }
  .item.active svg { color: var(--accent); }
  .spacer { flex-grow: 1; }
  .inbox { margin: 0 12px 10px; padding: 14px 12px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 9px; }
  .inbox-title { font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); }
  .inbox .row { display: flex; align-items: center; justify-content: space-between; font-size: 12px; }
  .inbox .num { font-size: 13px; color: var(--text); }
  .shortcuts { padding: 0 24px; display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--muted); }
</style>
