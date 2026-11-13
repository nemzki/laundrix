import { expect, test, type Page } from '@playwright/test'

async function login(page: Page, role: 'admin' | 'staff' = 'admin') {
  await page.goto('/auth/login', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('html')).toHaveAttribute('data-theme-preference', /light|dark|system/)
  if (role === 'staff') await page.getByRole('tab', { name: 'Staff', exact: true }).click()
  await page.locator(`#${role}-identifier`).fill(role === 'admin' ? 'browseradmin' : 'staff@example.test')
  await page.locator(`#${role}-password`).fill('Browser-Test-Password!42')
  await page.locator(`form[data-auth-form=${role}] button[type=submit]`).click()
  await expect(page).toHaveURL(/dashboard/)
  await expect(page.locator('#laundrix-dashboard')).toHaveAttribute('data-ready', 'true')
}
const picker = (page: Page) => page.locator('[data-theme-picker]').filter({ visible: true }).first()
async function choose(page: Page, value: 'light' | 'dark' | 'system') {
  const original = page.url()
  if (new URL(original).pathname === '/') {
    await picker(page).locator('[data-theme-trigger]').click()
    await picker(page).locator(`[data-theme-option=${value}]`).click()
  } else {
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await page.locator(`[data-theme-preferences] [data-theme-option=${value}]`).click()
    if (new URL(original).pathname !== '/settings') await page.goto(original, { waitUntil: 'domcontentloaded' })
  }
  await expect(page.locator('html')).toHaveAttribute('data-theme-preference', value)
}
async function darkSurface(page: Page, selector: string) {
  const node = page.locator(selector).first()
  await expect(node).toBeVisible()
  expect(await node.evaluate(el => getComputedStyle(el).backgroundColor)).toBe('rgb(30, 41, 59)')
}

test('system default, live OS changes, explicit preference, persistence, keyboard and cross-tab synchronization', async ({ page, context }) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await login(page)
  await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'dark')
  await expect(page.locator('html')).toHaveAttribute('data-theme-preference', 'system')
  const gear = page.getByRole('link', { name: 'Personal Settings', exact: true }).filter({ visible: true }).first()
  await expect(gear).toHaveAttribute('title', 'Personal Settings')
  await gear.focus(); await page.keyboard.press('Enter')
  const appearance = page.locator('[data-theme-preferences]')
  await appearance.locator('[data-theme-option=system]').focus()
  await page.keyboard.press('Home')
  await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'light')
  await expect(appearance.locator('[data-theme-option=light]')).toBeFocused()
  await page.emulateMedia({ colorScheme: 'light' })
  await choose(page, 'dark')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'dark')
  expect(await page.evaluate(() => localStorage.getItem('laundrix-theme'))).toBe('dark')
  await page.goto('/orders/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'dark')
  await choose(page, 'system')
  await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'light')
  await page.emulateMedia({ colorScheme: 'dark' })
  await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'dark')
  await page.goto('/settings', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-theme-preferences] [data-theme-option=system]')).toHaveAttribute('aria-checked', 'true')
  const other = await context.newPage()
  await other.goto('/orders/', { waitUntil: 'domcontentloaded' })
  await choose(other, 'light')
  await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'light')
  await other.close()
})

for (const role of ['admin', 'staff'] as const) for (const width of [320, 768, 1440]) {
  test(`dark internal routes and overlays: ${role} ${width}px`, async ({ page }) => {
    test.setTimeout(120000)
    const errors: string[] = []; page.on('pageerror', error => errors.push(error.message))
    await page.setViewportSize({ width, height: 1000 })
    await page.emulateMedia({ colorScheme: 'dark' })
    await login(page, role)
    await darkSurface(page, '.dashboard-card')
    if (width === 320) await page.getByRole('button', { name: 'More', exact: true }).click()
    await choose(page, 'dark')
    await expect(page.locator('[data-theme-picker]')).toHaveCount(0)
    const routes = role === 'admin'
      ? ['/dashboard/?ui=jinja', '/orders/new', '/orders/', '/orders/customers', '/admin/services/', '/admin/staff/', '/admin/staff/new', '/payments/outstanding', '/payments/', '/payments/summary', '/payments/settings']
      : ['/dashboard/?ui=jinja', '/orders/new', '/orders/', '/payments/outstanding']
    for (const route of routes) {
      expect((await page.goto(route, { waitUntil: 'domcontentloaded' }))?.status(), route).toBe(200)
      await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'dark')
      for (const selector of ['[data-manage-orders]', '[data-customer-directory]', '[data-outstanding]']) {
        if (await page.locator(selector).count()) await expect(page.locator(selector)).toHaveAttribute('data-state', 'ready')
      }
      for (const selector of ['#laundrix-catalog', '#laundrix-staff']) {
        if (await page.locator(selector).count()) await expect(page.locator(selector)).toHaveAttribute('data-ready', 'true')
      }
      expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor), route).toBe('rgb(15, 23, 42)')
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), route).toBe(true)
      // Visible large white rectangles identify unthemed panels, excluding images and protected identity.
      const white = await page.evaluate(() => Array.from(document.querySelectorAll('main *, .content *')).filter(el => {
        if (el.closest('.idv-card, #dashboard-preserved-identity') || el.matches('img, svg, svg *, canvas, input[type=checkbox]')) return false
        const rect = el.getBoundingClientRect(), style = getComputedStyle(el)
        return rect.width > 70 && rect.height > 25 && style.visibility !== 'hidden' && style.backgroundColor === 'rgb(255, 255, 255)'
      }).map(el => el.tagName + '.' + el.className).slice(0, 10))
      expect(white, route).toEqual([])
      if (route === '/orders/') {
        const href = await page.locator('a[data-order-summary]').first().getAttribute('href')
        expect(href).toBeTruthy(); await page.goto(href!, { waitUntil: 'domcontentloaded' })
        await darkSurface(page, '#payment')
        await page.emulateMedia({ media: 'print' })
        expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgb(255, 255, 255)')
        await page.emulateMedia({ media: 'screen' })
      }
      if (route === '/payments/outstanding') {
        await page.locator('[data-ob-payment]').first().click()
        await darkSurface(page, '#recordPaymentModal .modal-content')
        await expect(page.locator('#recordPaymentModal input[name=amount]').first()).toBeVisible()
        await page.locator('#recordPaymentModal [data-bs-dismiss=modal]').first().click()
      }
      if (route === '/admin/staff/') {
        await page.locator('#staff-action-react').getByRole('button', { name: 'Add Staff', exact: true }).click()
        await darkSurface(page, '.staff-dialog')
        await page.keyboard.press('Escape')
        await page.locator('[data-staff-row]').first().getByRole('button', { name: /Actions for/ }).click()
        await page.getByRole('menuitem', { name: 'View Details', exact: true }).click()
        await darkSurface(page, '.staff-sheet')
        await page.keyboard.press('Escape')
      }
    }
    await page.screenshot({ path: `test-results/dashboard/theme-${role}-${width}.png`, fullPage: true })
    if (role === 'staff') expect((await page.request.get('/orders/customers')).status()).toBe(403)
    expect(errors).toEqual([])
  })
}

test('server dashboard has prepaint theme and selector before React loads', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.route('**/react-dashboard/dashboard.js', route => route.abort())
  await page.goto('/auth/login', { waitUntil: 'domcontentloaded' })
  await page.locator('#admin-identifier').fill('browseradmin')
  await page.locator('#admin-password').fill('Browser-Test-Password!42')
  await page.locator('form[data-auth-form=admin] button[type=submit]').click()
  await expect(page.locator('#laundrix-dashboard')).toHaveAttribute('data-renderer', 'server')
  await darkSurface(page, '.dashboard-card')
  await choose(page, 'light')
  await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'light')
})

test('stored theme applies to public pages while the printable stub stays isolated', async ({ page, browser }) => {
  test.setTimeout(60000)
  await login(page)
  await choose(page, 'dark')
  await page.goto('/orders/', { waitUntil: 'domcontentloaded' })
  const href = await page.locator('a[data-order-summary]').first().getAttribute('href')
  await page.goto(href! + '/stub', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('html')).not.toHaveAttribute('data-lx-theme')
  await expect(page.locator('script[src$="/theme.js"]')).toHaveCount(0)
  const publicPage = await browser.newPage()
  await publicPage.addInitScript(() => localStorage.setItem('laundrix-theme', 'dark'))
  for (const url of ['/', '/auth/login', '/staff/login']) {
    await publicPage.goto('http://127.0.0.1:8771' + url, { waitUntil: 'domcontentloaded' })
    await expect(publicPage.locator('html')).toHaveAttribute('data-lx-theme', 'dark')
    await expect(publicPage.locator('link[href$="/theme.css"]')).toHaveCount(1)
    expect(await publicPage.locator('body').evaluate(el => getComputedStyle(el).backgroundColor)).toBe('rgb(15, 23, 42)')
  }
  await publicPage.close()
})

for (const role of ['admin', 'staff'] as const) {
  test(`landing preference survives login, navigation, refresh and logout: ${role}`, async ({ page }) => {
    test.setTimeout(90000)
    await page.emulateMedia({ colorScheme: 'light' })
    // Record the resolved state as soon as the body exists, before React mounts.
    await page.addInitScript(() => {
      const observer = new MutationObserver(() => {
        if (!document.body) return
        document.documentElement.dataset.themeAtBody = document.documentElement.dataset.lxTheme || 'missing'
        observer.disconnect()
      })
      observer.observe(document, { childList: true, subtree: true })
    })
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await choose(page, 'dark')
    await page.locator('[data-sign-in]').first().click()
    await expect(page.locator('html')).toHaveAttribute('data-theme-at-body', 'dark')
    await expect(page.locator('.lx-auth__input').first()).toHaveCSS('background-color', 'rgb(37, 50, 72)')
    await login(page, role)
    await expect(page.locator('html')).toHaveAttribute('data-theme-at-body', 'dark')
    for (const route of ['/orders/', '/payments/outstanding', '/dashboard/']) {
      await page.goto(route, { waitUntil: 'domcontentloaded' })
      await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'dark')
      await expect(page.locator('html')).toHaveAttribute('data-theme-at-body', 'dark')
    }
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'dark')
    await page.getByRole('button', { name: 'Logout', exact: true }).filter({ visible: true }).first().click()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'dark')
    await choose(page, 'light')
    await page.locator('[data-sign-in]').first().click()
    await expect(page.locator('html')).toHaveAttribute('data-theme-at-body', 'light')
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await choose(page, 'system')
    await page.emulateMedia({ colorScheme: 'dark' })
    await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'dark')
    await page.emulateMedia({ colorScheme: 'light' })
    await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'light')
    await page.locator('[data-sign-in]').first().click()
    await page.emulateMedia({ colorScheme: 'dark' })
    await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'dark')
    await expect(page.locator('html')).toHaveAttribute('data-theme-preference', 'system')
  })
}

test('explicit Light restores all Admin modules even when the OS is Dark', async ({ page }) => {
  test.setTimeout(90000)
  await page.emulateMedia({ colorScheme: 'dark' })
  await login(page)
  await choose(page, 'light')
  for (const route of ['/dashboard/', '/dashboard/?ui=jinja', '/orders/new', '/orders/', '/orders/customers', '/admin/services/', '/admin/staff/', '/admin/staff/new', '/payments/outstanding', '/payments/', '/payments/summary', '/payments/settings']) {
    await page.goto(route, { waitUntil: 'domcontentloaded' })
    await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'light')
    await expect(page.locator('html')).not.toHaveClass(/dark/)
    expect(await page.locator('body').evaluate(el => getComputedStyle(el).getPropertyValue('--lx-paint-surface').trim())).toBe('')
    expect(await page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor)).not.toBe('rgb(15, 23, 42)')
  }
})

for (const width of [320, 1440]) {
  test(`shared public palette and login form readability at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('html')).toHaveAttribute('data-theme-preference', 'system')
    await expect(page.locator('html')).toHaveClass(/dark/)
    await page.locator('#about').scrollIntoViewIfNeeded()
    await darkSurface(page, '.counter-receipt')
    await page.getByRole('button', { name: 'Change Theme', exact: true }).click()
    await darkSurface(page, '.lx-theme-menu')
    await page.keyboard.press('Escape')
    await expect(page.locator('#cta-heading')).toHaveCSS('color', 'rgb(241, 245, 249)')
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }))
    await page.screenshot({ path: `test-results/theme-sync/landing-dark-${width}.png`, fullPage: true })
    for (const url of ['/auth/login', '/staff/login']) {
      await page.goto(url, { waitUntil: 'domcontentloaded' })
      await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'dark')
      await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(15, 23, 42)')
      const input = page.locator('input[type=password]').first()
      await expect(input).toHaveCSS('color', 'rgb(241, 245, 249)')
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await page.screenshot({ path: `test-results/theme-sync/login-${url.includes('/auth/') ? 'unified' : 'legacy'}-dark-${width}.png`, fullPage: true })
    }
  })
}

test('catalog select portals, real validation errors and staff dropdowns share dark tokens', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await login(page)
  await page.goto('/admin/services/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('#laundrix-catalog')).toHaveAttribute('data-ready', 'true')
  await page.locator('#catalog-action-react').getByRole('button').click()
  await darkSurface(page, '.catalog-dialog')
  const dialog = page.locator('.catalog-dialog')
  await dialog.getByLabel('Service Name', { exact: true }).fill('Theme validation check')
  await dialog.getByLabel('Code', { exact: true }).fill('theme_validation_check')
  await dialog.getByLabel('Price', { exact: true }).fill('12.50')
  await dialog.getByLabel('Pricing Unit', { exact: true }).click()
  await darkSurface(page, '[role=listbox]')
  await page.getByRole('option', { name: 'Per Piece', exact: true }).click()
  await dialog.getByRole('textbox', { name: 'Category', exact: true }).fill('Theme check')
  await dialog.locator('summary').click()
  await dialog.getByLabel('Image Path (Optional)', { exact: true }).fill('https://invalid.example/image.png')
  await dialog.getByRole('button', { name: 'Add Service', exact: true }).click()
  const validation = dialog.getByRole('alert').first()
  await expect(validation).toContainText('local path')
  await expect(validation).toHaveCSS('color', 'rgb(252, 165, 165)')
  await page.keyboard.press('Escape')
  await page.goto('/admin/staff/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('#laundrix-staff')).toHaveAttribute('data-ready', 'true')
  await page.locator('[data-staff-row]').first().getByRole('button', { name: /Actions for/ }).click()
  await darkSurface(page, '.staff-menu')
  await page.keyboard.press('Escape')
})
