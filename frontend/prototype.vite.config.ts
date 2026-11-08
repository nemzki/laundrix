import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { defineConfig, mergeConfig } from 'vite'
import existing from './vite.config.ts'

// Uses the existing frontend toolchain; this is a component preview, not a second app.
export default mergeConfig({ ...existing, plugins: existing.plugins?.filter(plugin => (plugin as { name?: string }).name !== 'scope-flask-css') }, defineConfig({
  plugins: [{ name: 'scope-reference-preview', writeBundle() {
    execFileSync(process.execPath, ['scripts/scope-css.mjs', 'prototype-dist/prototype.css'], { stdio: 'inherit' })
  } }],
  build: { outDir: 'prototype-dist', rolldownOptions: { input: resolve(import.meta.dirname, 'prototype.html'),
    output: { entryFileNames: 'prototype.js', assetFileNames: asset => asset.names.some(name => name.endsWith('.css')) ? 'prototype.css' : 'assets/[name]-[hash][extname]' } } },
  preview: { host: '127.0.0.1', port: 8773, strictPort: true },
}))
