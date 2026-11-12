import { defineConfig, mergeConfig } from 'vite'
import existing from './vite.config.ts'
import { scopeCss } from './scripts/scope-css.mjs'

export default mergeConfig({ ...existing, plugins: existing.plugins?.filter(plugin => (plugin as { name?: string }).name !== 'scope-flask-css') }, defineConfig({
  plugins: [{ name: 'scope-catalog', async writeBundle() { await scopeCss('../app/core/static/react-catalog/catalog.css') } }],
  build: { outDir: '../app/core/static/react-catalog', rolldownOptions: {
    input: 'src/catalog/main.tsx', output: { entryFileNames: 'catalog.js', assetFileNames: 'catalog.[ext]' },
  } },
}))
