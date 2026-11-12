import { scopeCss } from './scripts/scope-css.mjs'
import { defineConfig, mergeConfig } from 'vite'
import existing from './vite.config.ts'
export default mergeConfig({ ...existing, plugins: existing.plugins?.filter(plugin => (plugin as { name?: string }).name !== 'scope-flask-css') }, defineConfig({
  plugins: [{ name: 'scope-dashboard', async writeBundle() {
    await scopeCss('../app/core/static/react-dashboard/dashboard.css')
  } }],
  build: { outDir: '../app/core/static/react-dashboard', rolldownOptions: {
    input: 'src/dashboard/main.tsx', output: { entryFileNames: 'dashboard.js', assetFileNames: asset => asset.names.some(name => name.endsWith('.woff2')) ? 'fonts/[name][extname]' : 'dashboard.[ext]' },
  } },
}))
