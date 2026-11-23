import { expect, test, type Page } from '@playwright/test'

async function checkGeist(page: Page) {
  expect(await page.evaluate(async () => {
    const faces = await document.fonts.load('400 16px "Geist Sans"')
    return faces.length > 0 && faces.every(face => face.status === 'loaded')
  })).toBe(true)
  await page.evaluate(() => document.fonts.ready)
  await expect(page.locator('body')).toHaveCSS('font-family', /^"Geist Sans",/)
  expect(await page.evaluate(() => document.fonts.check('400 16px "Geist Sans"') && document.fonts.check('700 16px "Geist Sans"'))).toBe(true)
  await expect(page.locator('link[href*="css/fonts.css"]')).toHaveCount(1)
  expect(await page.evaluate(() => [...document.fonts].filter(font => font.family.replaceAll('"', '') === 'Geist Sans').length)).toBe(2)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  const control = page.locator('input:not([type=hidden]), select, textarea, button').filter({ visible: true }).first()
  if (await control.count()) expect(await control.evaluate(element => getComputedStyle(element).fontFamily)).toMatch(/Geist Sans/)
}

test('shared Geist loads once across public, Admin, Staff, React and receipt layouts', async ({ page }) => {
  test.setTimeout(60000)
  const failedFonts: string[] = []
  page.on('requestfailed', request => {
    // Redirects/page changes may cancel an in-flight preload; real load failures still fail.
    if (request.resourceType() === 'font' && request.failure()?.errorText !== 'net::ERR_ABORTED') failedFonts.push(request.url())
  })
  await page.goto('/')
  await expect(page.locator('body')).toHaveCSS('font-family', /^Inter,/)
  await expect(page.locator('link[href*="css/fonts.css"]')).toHaveCount(0)
  for (const path of ['/auth/login', '/track/not-a-valid-link']) {
    await page.goto(path)
    await checkGeist(page)
  }
  await page.goto('/auth/login')
  await page.locator('#identifier').fill('browseradmin')
  await page.locator('#password').fill('Browser-Test-Password!42')
  await page.locator('[data-auth-form] button[type=submit]').click()
  await expect(page).toHaveURL(/dashboard/)
  for (const path of ['/dashboard/', '/orders/', '/orders/new', '/orders/customers', '/admin/services/', '/payments/outstanding', '/payments/', '/payments/summary', '/payments/settings', '/admin/staff/', '/admin/staff/new']) {
    const response = await page.goto(path)
    expect(response!.status(), path).toBe(200)
    await checkGeist(page)
    if (path === '/dashboard/' && await page.locator('canvas#dashStatusChart').count()) {
      await expect.poll(() => page.evaluate("Object.values(window.Chart?.instances || {}).filter(chart => chart.options.plugins.legend.labels.font.family.includes('Geist Sans')).length")).toBeGreaterThan(0)
    }
  }
  await page.goto('/payments/outstanding')
  await expect(page.locator('.ob-reference').filter({ visible: true }).first()).toHaveCSS('font-family', /^"Geist Mono",/)
  await page.goto('/orders/')
  await expect(page.locator('[data-manage-orders]')).toHaveAttribute('data-state', 'ready')
  await page.getByRole('link', { name: /^View order/ }).filter({ visible: true }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Order Summary' })
  await expect(dialog).toHaveCSS('font-family', /^"Geist Sans",/)
  const printStub = dialog.getByRole('link', { name: 'Print Stub' })
  await expect(printStub).toBeVisible()
  const stubUrl = await printStub.getAttribute('href')
  await page.goto(stubUrl!)
  await checkGeist(page)
  await page.emulateMedia({ media: 'print' })
  await expect(page.locator('.stub')).toHaveCSS('font-family', /^"Geist Sans",/)
  await expect(page.locator('.stub-toolbar')).toBeHidden()
  expect(await page.locator('.stub').evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
  await page.emulateMedia({ media: 'screen' })
  await page.evaluate(() => document.fonts.load('italic 400 16px "Geist Sans"'))
  expect(await page.evaluate(() => document.fonts.check('italic 400 16px "Geist Sans"'))).toBe(true)
  expect(await page.evaluate(async () => {
    const faces = await document.fonts.load('italic 400 13px "Geist Mono"')
    return faces.length > 0 && faces.every(face => face.status === 'loaded')
  })).toBe(true)

  // A separate authenticated Staff session exercises the retained Jinja shell.
  await page.context().clearCookies()
  await page.goto('/auth/login')
  await page.locator('#identifier').fill('staff@example.test')
  await page.locator('#password').fill('Browser-Test-Password!42')
  await page.locator('[data-auth-form] button[type=submit]').click()
  await expect(page).toHaveURL(/dashboard/)
  for (const path of ['/dashboard/', '/orders/', '/orders/new']) {
    await page.goto(path)
    await checkGeist(page)
  }
  expect(failedFonts).toEqual([])
})
