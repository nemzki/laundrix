import { defineConfig } from '@playwright/test'
import dashboard from './playwright.dashboard.config'
export default defineConfig({
  ...dashboard,
  outputDir: './test-results/profile-editing',
  testMatch: ['**/profile-editing.spec.ts','**/personal-settings.spec.ts','**/theme.spec.ts'],
})
