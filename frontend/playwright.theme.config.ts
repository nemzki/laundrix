import { defineConfig } from '@playwright/test'
import dashboard from './playwright.dashboard.config'

// Exercise existing real Flask workflows with System resolving to Dark.
export default defineConfig({
  ...dashboard,
  outputDir: './test-results/theme-regression',
  use: { ...dashboard.use, colorScheme: 'dark' },
  testMatch: ['**/order-details.spec.ts', '**/staff.spec.ts', '**/catalog.spec.ts', '**/dashboard.spec.ts', '**/customers.spec.ts', '**/outstanding.spec.ts'],
})
