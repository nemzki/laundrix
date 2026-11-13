import { defineConfig } from '@playwright/test'
import dashboard from './playwright.dashboard.config'
export default defineConfig({
  ...dashboard,
  outputDir: './test-results/verification',
  testMatch: '**/verification.spec.ts',
  use: { ...dashboard.use, baseURL: 'http://127.0.0.1:8773' },
  webServer: { command: '..\\.venv\\Scripts\\python.exe ..\\tests\\frontend\\serve_verification.py',
    url: 'http://127.0.0.1:8773/auth/login', reuseExistingServer: false, timeout: 45000 },
})
