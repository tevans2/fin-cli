import { readable } from 'svelte/store'

export type Route = 'overview' | 'cashflow' | 'trends' | 'recurring' | 'explorer' | 'merchants'

const ROUTES: Route[] = ['overview', 'cashflow', 'trends', 'recurring', 'explorer', 'merchants']

function parse(): Route {
  const h = location.hash.replace(/^#\/?/, '').split('?')[0]
  return (ROUTES.includes(h as Route) ? h : 'overview') as Route
}

export const route = readable<Route>(parse(), (set) => {
  const on = () => set(parse())
  window.addEventListener('hashchange', on)
  return () => window.removeEventListener('hashchange', on)
})

export function go(r: Route) {
  location.hash = `#/${r === 'overview' ? '' : r}`
}

// vim-style `g` then a letter (gc, gt, gr, gx, gm, go) jumps between pages.
const KEY: Record<string, Route> = { o: 'overview', c: 'cashflow', t: 'trends', r: 'recurring', x: 'explorer', m: 'merchants' }

export function installKeys(onHelp: () => void) {
  let pending = false
  let timer: ReturnType<typeof setTimeout>
  window.addEventListener('keydown', (e) => {
    const el = e.target as HTMLElement
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return
    if (e.metaKey || e.ctrlKey || e.altKey) return
    if (e.key === '?') { onHelp(); return }
    if (pending) {
      pending = false
      clearTimeout(timer)
      const r = KEY[e.key]
      if (r) { e.preventDefault(); go(r) }
      return
    }
    if (e.key === 'g') {
      pending = true
      timer = setTimeout(() => (pending = false), 700)
    }
  })
}
