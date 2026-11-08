import { defineConfig, mergeConfig } from 'vite'
import existing from './vite.config.ts'
import { scopeCss } from './scripts/scope-css.mjs'

export default mergeConfig({ ...existing, plugins: existing.plugins?.filter(plugin => (plugin as { name?: string }).name !== 'scope-flask-css') }, defineConfig({
  plugins: [{ name: 'scope-staff', async writeBundle() { await scopeCss('../app/core/static/react-staff/staff.css') } }],
  build: { outDir: '../app/core/static/react-staff', rolldownOptions: {
    input: 'src/staff/main.tsx', output: { entryFileNames: 'staff.js', assetFileNames: 'staff.[ext]' },
  } },
}))
