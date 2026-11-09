import { expect, test } from '@playwright/test'

const routes = ['/admin/services/', '/dashboard/', '/orders/new', '/orders/', '/payments/outstanding', '/orders/customers', '/admin/staff/', '/payments/', '/payments/summary', '/payments/settings']

for (const width of [1920, 1440, 1024, 768, 390]) test(`Admin workspace alignment ${width}px`, async ({ page }) => {
  test.setTimeout(180000)
  page.setDefaultTimeout(10000)
  await page.setViewportSize({ width, height: 1000 })
  await page.goto('/auth/login')
  await page.locator('#admin-identifier').fill('browseradmin')
  await page.locator('#admin-password').fill('Browser-Test-Password!42')
  await page.locator('form[data-auth-form=admin] button[type=submit]').click()
  await expect(page).toHaveURL(/dashboard/)
  const gutter = width >= 1024 ? 32 : width >= 768 ? 24 : 16
  for (const route of routes) {
    await page.goto(route)
    for (const selector of ['#laundrix-dashboard', '#laundrix-catalog', '#laundrix-staff']) {
      if (await page.locator(selector).count()) await expect(page.locator(selector)).toHaveAttribute('data-ready', 'true')
    }
    const content = page.locator('main.content, .dashboard-content')
    const check = async (collapsed = false) => {
      const box = (await content.boundingBox())!
      const offset = width >= 768 && !collapsed ? 256 : 0
      expect(box.x, route).toBeCloseTo(offset, 0)
      expect(box.width, route).toBeCloseTo(width - offset, 0)
      const padding = await content.evaluate(el => [getComputedStyle(el).paddingLeft, getComputedStyle(el).paddingRight])
      expect(padding, route).toEqual([`${gutter}px`, `${gutter}px`])
      const headerPadding = await page.locator('.admin-topbar, [data-slot=sidebar-inset] > header').evaluate(el => getComputedStyle(el).paddingLeft)
      expect(headerPadding, route).toBe(`${gutter}px`)
      const heading = await content.locator('h1').first().boundingBox()
      expect(heading!.x, route).toBeCloseTo(offset + gutter, 0)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), route).toBe(true)
    }
    await check()
    if (route === '/payments/') {
      const panel = (await page.locator('.payment-records-panel').boundingBox())!
      const box = (await content.boundingBox())!
      expect(panel.x).toBeCloseTo(box.x + gutter, 0)
      expect(panel.width).toBeCloseTo(box.width - 2 * gutter, 0)
      const controls = await page.locator('.payment-records-filters .input').evaluateAll(elements => elements.map(el => {
        const rect = el.getBoundingClientRect()
        return { height: rect.height, width: rect.width, left: rect.left, right: rect.right }
      }))
      expect(controls).toHaveLength(5)
      for (const control of controls) {
        expect(control.height).toBe(38)
        expect(control.width).toBeGreaterThanOrEqual(160)
        expect(control.left).toBeGreaterThanOrEqual(panel.x)
        expect(control.right).toBeLessThanOrEqual(panel.x + panel.width)
      }
      const table = page.locator('.payment-records-table')
      await expect(table).toBeVisible()
      expect(await table.locator('th.num').evaluate(el => getComputedStyle(el).textAlign)).toBe('right')
      expect(await table.boundingBox()).not.toBeNull()
      await page.getByLabel('Method', { exact: true }).selectOption('cash')
      await page.getByLabel('Type', { exact: true }).selectOption('payment')
      await page.getByLabel('From', { exact: true }).fill('2020-01-01')
      await page.getByRole('button', { name: 'Filter', exact: true }).click()
      await expect(page).toHaveURL(/method=cash/)
      await expect(page.getByLabel('Type', { exact: true })).toHaveValue('payment')
      await expect(page.getByLabel('From', { exact: true })).toHaveValue('2020-01-01')
      for (const cell of await table.locator('tbody tr td:nth-child(3)').all()) await expect(cell).toHaveText('Cash')
      await expect(table.locator('tbody tr').first()).toBeVisible()
      await page.getByRole('link', { name: 'Clear', exact: true }).click()
      await expect(page.getByLabel('Method', { exact: true })).toHaveValue('')
      await check()
    }
    await page.screenshot({ path: `test-results/admin-workspace/workspace-${width}-${route.replaceAll('/', '-')}.png`, fullPage: true })
    if (width >= 768) {
      const toggle = page.locator('[data-admin-sidebar-toggle], [data-slot=sidebar-trigger]')
      await toggle.click()
      await expect.poll(async () => (await content.boundingBox())!.x).toBe(0)
      await check(true)
      await toggle.click()
      await expect.poll(async () => (await content.boundingBox())!.x).toBe(256)
      await check()
    }
  }
})

