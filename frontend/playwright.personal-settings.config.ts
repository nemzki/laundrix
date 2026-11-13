import { defineConfig } from '@playwright/test'
import dashboard from './playwright.dashboard.config'

export default defineConfig({
  ...dashboard,
  outputDir: './test-results/personal-settings',
  testMatch: ['**/personal-settings.spec.ts', '**/theme.spec.ts', '**/dashboard.spec.ts'],
})
