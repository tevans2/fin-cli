<script lang="ts">
  export let title: string
</script>

<header class="head">
  <h1>{title}</h1>
  <p>Coming soon</p>
</header>
<div class="card empty">
  <p>{title} lands in the next increment.</p>
</div>

<style>
  .head h1 { margin: 0; font-size: 20px; font-weight: 600; letter-spacing: -0.01em; }
  .head p { margin: 6px 0 0; font-size: 12px; color: var(--muted); }
  .empty { padding: 48px; display: flex; align-items: center; justify-content: center; color: var(--muted); }
</style>
