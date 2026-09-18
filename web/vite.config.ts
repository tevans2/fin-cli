import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

// In dev, proxy API calls to the running `fin serve` and inject its bearer token
// (read from ~/.config/fin/runtime.json) so the browser needs no secret.
function runtime(): { url: string; token: string } {
  const dir = process.env.FIN_CONFIG_DIR
    || (process.env.XDG_CONFIG_HOME ? join(process.env.XDG_CONFIG_HOME, 'fin') : join(homedir(), '.config', 'fin'))
  try {
    const rt = JSON.parse(readFileSync(join(dir, 'runtime.json'), 'utf8'))
    return { url: rt.url, token: rt.token }
  } catch {
    return { url: process.env.FIN_API_URL || 'http://127.0.0.1:8765', token: process.env.FIN_API_TOKEN || '' }
  }
}

// The API paths the SPA calls; everything else is client-side routing.
const API = ['/status', '/analysis', '/transactions', '/merchants', '/verify', '/banks', '/taxonomy', '/health', '/web-config']

export default defineConfig(() => {
  const rt = runtime()
  const proxy: Record<string, any> = {}
  for (const p of API) {
    proxy[p] = {
      target: rt.url,
      changeOrigin: true,
      configure: (proxyServer: any) => {
        proxyServer.on('proxyReq', (proxyReq: any) => {
          if (rt.token) proxyReq.setHeader('Authorization', `Bearer ${rt.token}`)
        })
      },
    }
  }
  return {
    plugins: [svelte()],
    server: { port: 5317, proxy },
    build: { outDir: 'dist', emptyOutDir: true },
  }
})
