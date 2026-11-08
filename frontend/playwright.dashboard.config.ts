import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './tests/dashboard', outputDir: './test-results/dashboard', workers: 1,
  use: { baseURL: 'http://127.0.0.1:8771', channel: 'msedge', headless: true },
  webServer: { command: '..\\.venv\\Scripts\\python.exe ..\\tests\\frontend\\serve_react.py',
    url: 'http://127.0.0.1:8771/auth/login', reuseExistingServer: false, timeout: 45000 },
})
