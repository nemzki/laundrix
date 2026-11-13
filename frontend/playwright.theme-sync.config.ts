import { defineConfig } from '@playwright/test'
import dashboard from './playwright.dashboard.config'

export default defineConfig({
  ...dashboard,
  testDir: './tests',
  outputDir: './test-results/theme-sync',
  testMatch: ['**/dashboard/theme.spec.ts', '**/landing/landing.spec.ts'],
})
