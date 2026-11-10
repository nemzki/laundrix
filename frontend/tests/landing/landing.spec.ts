import { expect, test, type Page } from '@playwright/test'

async function open(page: Page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('html')).toHaveClass(/lp-enhanced/)
  await page.evaluate(() => document.fonts.ready)
}
async function revealAll(page: Page) {
  await page.evaluate(async () => {
    for (let y = 0; y < document.body.scrollHeight; y += 600) {
      window.scrollTo(0, y)
      await new Promise(resolve => setTimeout(resolve, 60))
    }
    await Promise.all([...document.images].map(image => image.decode()))
    window.scrollTo(0, 0)
  })
}

for (const width of [320, 390, 768, 1440]) {
  test(`approved landing layout, assets and controls at ${width}px`, async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
    page.on('response', response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`) })
    await page.setViewportSize({ width, height: 1000 })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await open(page)
    await expect(page).toHaveTitle('Laundrix — Laundry Management, Made Simple')
    await expect(page.locator('h1')).toHaveText('Laundry Management, Made Simple.')
    await expect(page.locator('main > section')).toHaveCount(6)
    await expect(page.locator('#features article')).toHaveCount(6)
    await expect(page.locator('[data-sign-in]')).toHaveCount(3)
    await expect(page.locator('header img.lx-logo__mark')).toHaveAttribute('src', '/core/static/images/mascot-original.svg')
    await expect(page.locator('footer img.lx-logo__mark')).toHaveAttribute('src', '/core/static/images/mascot-original.svg')
    for (const link of await page.locator('[data-sign-in]').all()) await expect(link).toHaveAttribute('href', '/auth/login')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(await page.locator('body').evaluate(el => getComputedStyle(el).fontFamily)).toContain('Inter')
    if (width < 768) {
      const toggle = page.getByRole('button', { name: 'Open menu', exact: true })
      await toggle.click()
      await expect(page.locator('#mobile-menu')).toBeVisible()
      await page.locator('#mobile-menu').getByRole('link', { name: 'Features', exact: true }).click()
      await expect(page.locator('#mobile-menu')).toBeHidden()
      await expect(page).toHaveURL(/#features$/)
      await page.getByRole('button', { name: 'Open menu', exact: true }).click()
      await page.keyboard.press('Escape')
      await expect(toggle).toBeFocused()
    } else {
      await expect(page.getByRole('navigation', { name: 'Main', exact: true })).toBeVisible()
      await expect(page.locator('[data-mobile-toggle]')).toBeHidden()
    }
    const titles = ['Register Customers', 'Create Laundry Orders', 'Monitor Progress & Payments', 'Complete & Release Orders']
    for (let index = 0; index < 4; index++) {
      await page.locator(`[data-workflow-step="${index}"]`).click()
      await expect(page.locator('[data-workflow-panel] h3')).toHaveText(titles[index])
      await expect(page.locator(`[data-workflow-step="${index}"]`)).toHaveAttribute('aria-current', 'step')
      await expect(page.locator('[data-workflow-progress]')).toHaveClass(new RegExp(`lp-progress-${index}`))
    }
    await page.locator('[data-workflow-step="0"]').focus()
    await page.keyboard.press('ArrowRight')
    await expect(page.locator('[data-workflow-step="1"]')).toBeFocused()
    await expect(page.locator('[data-workflow-panel] h3')).toHaveText(titles[1])
    const actual = { Orders: 'Manage Orders', Payments: 'Payment Records', Dashboard: 'Admin Dashboard' }
    for (const name of ['Orders', 'Payments', 'Dashboard'] as const) {
      await page.getByRole('tab', { name, exact: true }).click()
      await expect(page.getByRole('tabpanel').getByRole('heading', { name: actual[name], exact: true })).toBeVisible()
      await expect(page.getByRole('tab', { name, exact: true })).toHaveAttribute('aria-selected', 'true')
      await expect(page.locator('#preview .lp-original-screen')).toHaveAttribute('src', `/landing/static/previews/${name.toLowerCase()}.png`)
      await expect(page.locator('#preview .lp-original-screen')).toHaveAttribute('alt', new RegExp(actual[name]))
      await expect(page.locator('#preview .lp-preview-image-link')).toHaveAttribute('target', '_blank')
    }
    await page.getByRole('tab', { name: 'Dashboard', exact: true }).focus()
    await page.keyboard.press('End')
    await expect(page.getByRole('tab', { name: 'Payments', exact: true })).toBeFocused()
    await expect(page.getByRole('tabpanel').getByRole('heading', { name: 'Payment Records', exact: true })).toBeVisible()
    await page.locator('[data-workflow-step="0"]').click()
    await page.getByRole('tab', { name: 'Dashboard', exact: true }).click()
    await revealAll(page)
    expect(await page.locator('img').evaluateAll(images => images.every(image => image.complete && image.naturalWidth > 0))).toBe(true)
    expect(await page.locator('.reveal').evaluateAll(nodes => nodes.every(node => node.getAttribute('data-visible') === 'true'))).toBe(true)
    await page.screenshot({ path: `test-results/landing/landing-${width}.png`, fullPage: true })
    expect(errors).toEqual([])
  })
}

test('normal motion retains the reference float, bubble and reveal animations', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await open(page)
  await expect(page.locator('.animate-float').first()).toHaveCSS('animation-name', 'float')
  await expect(page.locator('.animate-bubble').first()).toHaveCSS('animation-name', 'bubble')
  await page.locator('#features').scrollIntoViewIfNeeded()
  await expect(page.locator('#features .reveal').first()).toHaveAttribute('data-visible', 'true')
  await expect(page.locator('#features .reveal').first()).toHaveCSS('opacity', '1')
})

for (const role of ['admin', 'staff'] as const) {
  test(`${role} sign-in uses the original authenticated session and role dashboard`, async ({ page }) => {
    await open(page)
    await page.locator('[data-sign-in]').first().click()
    await expect(page).toHaveURL(/\/auth\/login$/)
    await expect(page.locator('link[href*="landing"]')).toHaveCount(0)
    await expect(page.locator('#googleBtn')).toHaveAttribute('href', /\/auth\/google/)
    if (role === 'staff') await page.getByRole('tab', { name: 'Staff', exact: true }).click()
    await page.locator(`#${role}-identifier`).fill(role === 'admin' ? 'browseradmin' : 'staff@example.test')
    await page.locator(`#${role}-password`).fill('Browser-Test-Password!42')
    await page.locator(`form[data-auth-form=${role}] button[type=submit]`).click()
    await expect(page).toHaveURL(new RegExp(`/dashboard/${role}$`))
    await expect(page.locator('#laundrix-dashboard')).toHaveAttribute('data-ready', 'true')
    await page.goto('/')
    await expect(page).toHaveURL(/\/dashboard\/$/)
    await expect(page.locator('#laundrix-dashboard')).toHaveAttribute('data-dashboard-role', role)
    expect((await page.request.get('/orders/')).status()).toBe(200)
    if (role === 'staff') expect((await page.request.get('/admin/staff/')).status()).toBe(403)
  })
}

test('page remains readable and sign-in works without JavaScript', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false })
  const page = await context.newPage()
  await page.goto('http://127.0.0.1:8771/')
  await expect(page.locator('#features .reveal').first()).toHaveCSS('opacity', '1')
  await page.locator('[data-sign-in]').first().click()
  await expect(page).toHaveURL(/\/auth\/login$/)
  await context.close()
})
