import { expect, test, type Page } from '@playwright/test'
async function login(page: Page, role: 'admin' | 'staff') {
  await page.goto('/auth/login', { waitUntil: 'domcontentloaded' })
  if (role === 'staff') await page.getByRole('tab', { name: 'Staff', exact: true }).click()
  await page.locator(`#${role}-identifier`).fill(role === 'admin' ? 'browseradmin' : 'staff@example.test')
  await page.locator(`#${role}-password`).fill('Browser-Test-Password!42')
  await page.locator(`form[data-auth-form=${role}] button[type=submit]`).click()
  await expect(page.locator('#laundrix-dashboard')).toHaveAttribute('data-ready', 'true')
}
for (const role of ['admin','staff'] as const) for (const width of [320,768,1440]) for (const theme of ['light','dark'] as const) {
  test(`verification UI ${role} ${width}px ${theme}`, async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.setViewportSize({ width, height: 1000 })
    await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: theme })
    await login(page, role)
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await page.locator(`[data-theme-preferences] [data-theme-option=${theme}]`).click()
    await page.getByRole('link', { name: 'View Verification Details', exact: true }).click()
    await expect(page.locator('html')).toHaveAttribute('data-lx-theme', theme)
    await expect(page.locator('[data-idv-status]')).toHaveAttribute('data-idv-status', role === 'admin' ? 'not_started' : 'verified')
    await expect(page.locator('h1')).toBeVisible()
    await expect(page.locator('.idv-panel')).toHaveCSS('background-color', theme === 'dark' ? 'rgb(30, 41, 59)' : 'rgb(255, 255, 255)')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await expect(page.locator('iframe,input[type=file],input[capture]')).toHaveCount(0)
    await page.screenshot({ path: `test-results/verification/${role}-${theme}-${width}.png`, fullPage: true })
    if (role === 'admin') {
      await page.getByRole('link', { name: 'Start Verification', exact: true }).click()
      await expect(page).toHaveURL(/\/identity\/start$/)
      await expect(page.getByRole('checkbox')).not.toBeChecked()
      await expect(page.getByRole('checkbox')).toHaveAttribute('required', '')
      await expect(page.locator('.idv-notice')).toContainText('National Privacy Commission')
      await page.getByRole('button', { name: 'Continue to Verification', exact: true }).click()
      await expect(page).toHaveURL(/\/identity\/start$/)
      expect(await page.getByRole('checkbox').evaluate(el => (el as HTMLInputElement).validity.valueMissing)).toBe(true)
      await page.screenshot({ path: `test-results/verification/consent-${theme}-${width}.png`, fullPage: true })
    } else {
      await expect(page.getByRole('link', { name: /Start Verification|Continue Verification|Try Again/ })).toHaveCount(0)
    }
    await page.getByRole('link', { name: 'Back to Personal Settings', exact: true }).click()
    await expect(page).toHaveURL(/\/settings$/)
    await expect(page.locator('html')).toHaveAttribute('data-lx-theme', theme)
    expect(errors).toEqual([])
  })
}

test('consent POST keeps the existing hosted redirect and return flow', async ({ page }) => {
  await login(page, 'admin')
  await page.goto('/identity/start', { waitUntil: 'domcontentloaded' })
  const csrf = await page.locator('input[name=csrf_token]').inputValue()
  const response = await page.request.post('/identity/start', { form: { csrf_token: csrf, consent: 'on' }, maxRedirects: 0 })
  expect(response.status()).toBe(302)
  expect(response.headers().location).toMatch(/^https:\/\/verify\.didit\.me\//)
  await page.goto('/identity/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-idv-status]')).toHaveAttribute('data-idv-status', 'in_progress')
  await expect(page.getByRole('link', { name: 'Continue Verification', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Check Status', exact: true })).toBeVisible()
  await page.goto('/identity/return?status=Approved', { waitUntil: 'domcontentloaded' })
  await expect(page).toHaveURL(/\/identity\/$/)
  await expect(page.locator('[data-idv-status]')).not.toHaveAttribute('data-idv-status', 'verified')
})

test('System theme follows live OS changes on status and consent pages', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' })
  await login(page, 'admin')
  await page.goto('/settings', { waitUntil: 'domcontentloaded' })
  await page.locator('[data-theme-preferences] [data-theme-option=system]').click()
  for (const route of ['/identity/', '/identity/start']) {
    await page.goto(route, { waitUntil: 'domcontentloaded' })
    await expect(page.locator('html')).toHaveAttribute('data-theme-preference', 'system')
    await page.emulateMedia({ colorScheme: 'dark' })
    await expect(page.locator('.idv-panel')).toHaveCSS('background-color', 'rgb(30, 41, 59)')
    await page.emulateMedia({ colorScheme: 'light' })
    await expect(page.locator('.idv-panel')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'light')
  }
})
