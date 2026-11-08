import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { defineConfig, mergeConfig } from 'vite'
import existing from './vite.config.ts'

// Independent component preview: never replaces Flask's production orders entry.
export default mergeConfig({ ...existing, plugins: existing.plugins?.filter(plugin => (plugin as { name?: string }).name !== 'scope-flask-css') }, defineConfig({
  plugins: [{ name: 'scope-foundation-preview', writeBundle() {
    execFileSync(process.execPath, ['scripts/scope-css.mjs', 'foundation-dist/foundation.css'], { stdio: 'inherit' })
  } }],
  build: {
    outDir: 'foundation-dist',
    rolldownOptions: { input: resolve(import.meta.dirname, 'foundation.html'),
      output: { entryFileNames: 'foundation.js', assetFileNames: asset => asset.names.some(name => name.endsWith('.css')) ? 'foundation.css' : 'assets/[name]-[hash][extname]' } },
  },
  preview: { host: '127.0.0.1', port: 8772, strictPort: true },
}))
