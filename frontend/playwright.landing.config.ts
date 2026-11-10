import { defineConfig } from '@playwright/test'
import dashboard from './playwright.dashboard.config'

export default defineConfig({
  ...dashboard,
  testDir: './tests/landing',
  outputDir: './test-results/landing',
})
