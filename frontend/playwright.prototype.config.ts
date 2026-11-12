import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './tests/prototype', outputDir: './test-results/prototype', workers: 1,
  use: { baseURL: 'http://127.0.0.1:8773', channel: 'msedge', headless: true },
  webServer: { command: 'npm run preview:prototype', url: 'http://127.0.0.1:8773/prototype.html', reuseExistingServer: false },
})
