import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './tests/foundation', workers: 1,
  use: { baseURL: 'http://127.0.0.1:8772', channel: 'msedge', headless: true },
  webServer: { command: 'npx vite preview --config foundation.vite.config.ts', url: 'http://127.0.0.1:8772/foundation.html', reuseExistingServer: false },
})
