import { scopeCss } from './scripts/scope-css.mjs'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { fileURLToPath, URL } from 'node:url'
import { radixCsp } from './scripts/radix-csp.ts'
export default defineConfig({
 plugins: [radixCsp(), react(), tailwindcss(), { name: 'scope-flask-css', async writeBundle() { await scopeCss('../app/core/static/react/orders.css') } }],
 resolve: { alias: [
  { find: '@', replacement: fileURLToPath(new URL('./src', import.meta.url)) },
  { find: '@prototype', replacement: fileURLToPath(new URL('./src/prototype', import.meta.url)) },
  { find: /^react-remove-scroll-bar(?:\/constants)?$/, replacement: fileURLToPath(new URL('./src/lib/csp-scrollbar.tsx', import.meta.url)) },
 ] },
 base: './',
 build: {
  outDir: '../app/core/static/react', emptyOutDir: true,
  minify: true,
  cssTarget: 'chrome100',
  rolldownOptions: {
   input: 'src/main.tsx',
   output: { entryFileNames: 'orders.js', assetFileNames: 'orders.[ext]' },
  },
 },
})
