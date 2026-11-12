import { expect, test, type Page } from '@playwright/test'

async function login(page: Page, role: 'admin' | 'staff') {
  await page.goto('/auth/login')
  if (role === 'staff') await page.getByRole('tab', { name: 'Staff', exact: true }).click()
  await page.locator(`#${role}-identifier`).fill(role === 'admin' ? 'browseradmin' : 'staff@example.test')
  await page.locator(`#${role}-password`).fill('Browser-Test-Password!42')
  await page.locator(`form[data-auth-form=${role}] button[type=submit]`).click()
  await expect(page).toHaveURL(/\/dashboard\//)
}
async function assertDataParity(page: Page, role: 'admin' | 'staff') {
  const legacy = await page.request.get('/dashboard/?ui=jinja')
  expect(legacy.status()).toBe(200)
  const original = await page.evaluate(({ html, role }) => {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    const rows = [...doc.querySelectorAll(role === 'admin' ? '.lx-dash__kpi' : '.stat')]
    return { metrics: rows.map(row => ({
      label: row.querySelector(role === 'admin' ? '.lx-dash__kpi-label' : '.stat-label')!.textContent!.trim(),
      value: row.querySelector(role === 'admin' ? '.lx-dash__kpi-value' : '.stat-value')!.textContent!.trim(),
    })), links: [...doc.querySelectorAll('#app-sidebar .lx-nav__link')].map(link => ({ label: link.textContent!.trim(), href: link.getAttribute('href')! })) }
  }, { html: await legacy.text(), role })
  const payload = JSON.parse((await page.locator('#laundrix-dashboard-data').textContent())!)
  expect(payload.metrics.map((metric: { label: string; value: string }) => ({ label: metric.label, value: metric.value }))).toEqual(original.metrics)
  expect(payload.navigation.flatMap((group: { items: { label: string; url: string }[] }) => group.items.map(item => ({ label: item.label, href: item.url })))).toEqual(original.links)
  for (const metric of payload.metrics) {
    const card = page.locator(`[data-metric=${metric.key}]`)
    await expect(card.locator('.dashboard-metric-label')).toHaveText(metric.label)
    await expect(card.locator('.dashboard-metric-value')).toHaveText(metric.value)
  }
  for (const row of payload.recent) {
    const recent = page.locator('.dashboard-panels')
    await expect(recent.getByRole('link', { name: row.reference, exact: true }).filter({ visible: true })).toHaveAttribute('href', row.url)
    await expect(recent.getByText(row.status, { exact: true }).filter({ visible: true }).first()).toBeVisible()
  }
  for (const group of payload.navigation) for (const item of group.items) {
    const response = await page.request.get(item.url)
    expect(response.status(), item.label).toBe(200)
  }
  return payload
}

for (const width of [320, 1440]) test(`Shared Admin topbar and working toggle on every destination at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  await login(page, 'admin')
  await expect(page.locator('#laundrix-dashboard')).toHaveAttribute('data-renderer', 'react')
  const data = JSON.parse(await page.locator('#laundrix-dashboard-data').textContent() || '{}')
  await expect(page.getByRole('navigation', { name: 'Breadcrumb', exact: true })).toContainText('Admin Dashboard')
  const dashboardToggle = page.getByRole('button', { name: 'Toggle navigation', exact: true })
  await dashboardToggle.click()
  if (width < 768) {
    await expect(page.getByRole('dialog', { name: 'Sidebar', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
  } else {
    await expect(page.locator('[data-slot="sidebar"]')).toHaveAttribute('data-state', 'collapsed')
    await dashboardToggle.click()
    await expect(page.locator('[data-slot="sidebar"]')).toHaveAttribute('data-state', 'expanded')
  }
  for (const group of data.navigation) for (const item of group.items) {
    if (item.label === 'Dashboard') continue
    await page.goto(item.url)
    const header = page.getByRole('banner', { name: 'Admin page header' })
    await expect(header).toBeVisible()
    await expect(header.getByRole('navigation', { name: 'Breadcrumb' })).toHaveText(`${group.label}/${item.label}`)
    expect(await header.evaluate(element => element.getBoundingClientRect().height)).toBe(56)
    expect(await header.evaluate(element => getComputedStyle(element).fontFamily)).toContain('Inter')
    const toggle = header.getByRole('button', { name: 'Toggle sidebar' })
    if (width < 768) {
      await toggle.click()
      await expect(page.locator('#appNavDrawer')).toHaveClass(/show/)
      await expect(toggle).toHaveAttribute('aria-expanded', 'true')
      await page.keyboard.press('Escape')
      await expect(page.locator('#appNavDrawer')).not.toHaveClass(/show/)
      await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    } else {
      expect((await header.boundingBox())!.x).toBe(256)
      await toggle.click()
      await expect(page.locator('#app-sidebar')).toBeHidden()
      expect((await header.boundingBox())!.x).toBe(0)
      await expect(toggle).toHaveAttribute('aria-expanded', 'false')
      await toggle.click()
      await expect(page.locator('#app-sidebar')).toBeVisible()
      await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    }
    expect(await header.evaluate(element => element.getBoundingClientRect().right <= innerWidth)).toBe(true)
    await expect(toggle.locator('svg[data-icon="panel-left"]')).toHaveAttribute('stroke-width', '1.75')
  }
})

for (const width of [768, 1440]) test(`Admin sidebar matches dashboard on original Flask pages at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  await login(page, 'admin')
  await expect(page.locator('#laundrix-dashboard')).toHaveAttribute('data-renderer', 'react')
  const dashboard = page.locator('[data-slot="sidebar-container"]')
  await expect(dashboard).toBeVisible()
  const links = await dashboard.locator('nav a').evaluateAll(elements => elements.map(element => ({ text: element.textContent?.trim(), href: element.getAttribute('href') })))
  const dashboardWidth = (await dashboard.boundingBox())!.width
  const linkStyle = await dashboard.locator('nav a').first().evaluate(element => {
    const style = getComputedStyle(element)
    return { height: element.getBoundingClientRect().height, fontSize: style.fontSize, fontFamily: style.fontFamily }
  })
  for (const label of ['New Order', 'Customers', 'Payment Records']) {
    await page.goto(links.find(link => link.text === label)!.href!)
    const sidebar = page.locator('#app-sidebar')
    await expect(sidebar).toBeVisible()
    expect((await sidebar.boundingBox())!.width).toBe(dashboardWidth)
    expect(await sidebar.locator('nav a').evaluateAll(elements => elements.map(element => ({ text: element.textContent?.trim(), href: element.getAttribute('href') })))).toEqual(links)
    expect(await sidebar.locator('nav a').first().evaluate(element => {
      const style = getComputedStyle(element)
      return { height: element.getBoundingClientRect().height, fontSize: style.fontSize, fontFamily: style.fontFamily }
    })).toEqual(linkStyle)
    await expect(sidebar.locator('[aria-current="page"]')).toHaveCount(1)
    expect(await sidebar.locator('.lx-sidebar__brand').evaluate(element => element.getBoundingClientRect().height)).toBe(56)
    expect(await sidebar.locator('.lx-sidebar__avatar').evaluate(element => getComputedStyle(element).borderRadius)).toBe('8px')
    expect(await sidebar.locator('form').getAttribute('method')).toBe('post')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
})

for (const role of ['admin', 'staff'] as const) for (const width of [320, 768, 1440]) {
  test(`${role} dashboard parity, permissions, navigation and CSP at ${width}px`, async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => {
      Object.assign(window, { dashboardCsp: [] as string[] })
      document.addEventListener('securitypolicyviolation', event => (window as unknown as { dashboardCsp: string[] }).dashboardCsp.push(`${event.effectiveDirective}: ${event.blockedURI}`))
    })
    await page.setViewportSize({ width, height: 1000 })
    await login(page, role)
    await expect(page.locator('#laundrix-dashboard')).toHaveAttribute('data-renderer', 'react')
    await page.evaluate(() => document.fonts.ready)
    const data = await assertDataParity(page, role)
    expect(data.metrics).toHaveLength(role === 'admin' ? 8 : 7)
    if (role === 'staff') {
      expect(data.popular).toEqual([])
      expect(data.metrics.map((metric: { key: string }) => metric.key)).not.toContain('collected_today')
      for (const path of ['/dashboard/admin', '/orders/customers', '/admin/services/', '/admin/staff/', '/payments/', '/payments/summary', '/payments/settings']) {
        expect((await page.request.get(path)).status(), path).toBe(403)
      }
    } else {
      await expect(page.getByRole('heading', { name: 'Popular Services' })).toBeVisible()
      await expect(page.locator('[data-metric]').first()).toHaveCSS('border-radius', '14px')
      await expect(page.locator('.dashboard-metric-value').first()).toHaveCSS('font-size', '26px')
      await expect(page.locator('.dashboard-heading .dashboard-primary')).toHaveCSS('height', '36px')
      await expect(page.locator('.dashboard-currency').first()).toHaveCSS('text-align', 'right')
      for (const item of data.popular) await expect(page.locator('.dashboard-popular')).toContainText(item.name)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    if (width < 768) {
      const trigger = page.getByRole('button', { name: 'Toggle navigation' })
      await trigger.click()
      await expect(page.getByRole('dialog', { name: 'Sidebar', exact: true })).toBeVisible()
      await expect.poll(() => page.evaluate(() => Boolean(document.activeElement?.closest('[role=dialog]')))).toBe(true)
      await page.keyboard.press('Tab')
      await expect.poll(() => page.evaluate(() => Boolean(document.activeElement?.closest('[role=dialog]')))).toBe(true)
      await expect(page.getByRole('dialog').getByRole('link', { name: 'Dashboard', exact: true })).toHaveAttribute('aria-current', 'page')
      await page.keyboard.press('Escape')
      await expect(page.getByRole('dialog')).toHaveCount(0)
      await expect(trigger).toBeFocused()
      await page.getByRole('button', { name: 'More', exact: true }).click()
      await expect(page.getByRole('dialog')).toBeVisible()
      await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
      await expect(page.getByRole('dialog')).toHaveCount(0)
    } else {
      await expect(page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Dashboard', exact: true })).toHaveAttribute('aria-current', 'page')
      const toggle = page.getByRole('button', { name: 'Toggle navigation' })
      await toggle.click()
      await expect(page.locator('[data-slot=sidebar][data-collapsible=offcanvas]')).toHaveCount(1)
      await toggle.click()
      await expect.poll(() => page.locator('[data-slot=sidebar-gap]').evaluate(element => element.getBoundingClientRect().width)).toBe(256)
      await expect.poll(() => page.locator('[data-slot=sidebar-container]').evaluate(element => element.getBoundingClientRect().left)).toBe(0)
    }
    expect(await page.evaluate(() => (window as unknown as { dashboardCsp: string[] }).dashboardCsp)).toEqual([])
    expect(errors).toEqual([])
    await page.evaluate(() => { (document.activeElement as HTMLElement)?.blur(); window.scrollTo(0, 0) })
    await page.screenshot({ path: `test-results/dashboard/${role}-${width}.png` })
  })
}

test('server rendering stays usable without JavaScript and explicit rollback retains original page', async ({ page, browser }) => {
  await login(page, 'admin')
  const state = await page.context().storageState()
  const context = await browser.newContext({ javaScriptEnabled: false, storageState: state, viewport: { width: 320, height: 900 } })
  const serverPage = await context.newPage()
  await serverPage.goto('/dashboard/')
  await expect(serverPage.locator('#laundrix-dashboard')).toHaveAttribute('data-renderer', 'server')
  await expect(serverPage.locator('[data-metric]')).toHaveCount(8)
  await serverPage.locator('summary[aria-label="Open navigation"]').click()
  await expect(serverPage.locator('.dashboard-native-menu').getByRole('link', { name: 'Staff Management', exact: true })).toBeVisible()
  await serverPage.goto('/dashboard/?ui=jinja')
  await expect(serverPage.locator('.lx-dash')).toBeVisible()
  await expect(serverPage.locator('#laundrix-dashboard')).toHaveCount(0)
  await context.close()
})

test('failed stylesheet returns to Jinja; blocked script retains complete server page', async ({ page }) => {
  await login(page, 'admin')
  await page.route('**/react-dashboard/dashboard.css', route => route.abort())
  await page.goto('/dashboard/')
  await expect(page).toHaveURL(/ui=jinja/)
  await expect(page.locator('.lx-dash')).toBeVisible()
  await page.unroute('**/react-dashboard/dashboard.css')
  await page.route('**/react-dashboard/dashboard.js', route => route.abort())
  await page.goto('/dashboard/')
  await expect(page.locator('#laundrix-dashboard')).toHaveAttribute('data-renderer', 'server')
  await expect(page.locator('[data-metric]')).toHaveCount(8)
})

for (const role of ['admin', 'staff'] as const) for (const width of [320, 768, 1440]) test(`${role} first server paint and React retain geometry at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  await login(page, role)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/react-dashboard/dashboard.js', async route => { await gate; await route.continue() })
  await page.goto('/dashboard/', { waitUntil: 'commit' })
  await expect(page.locator('[data-metric]')).toHaveCount(role === 'admin' ? 8 : 7)
  await page.waitForFunction(() => Array.from(document.querySelectorAll<HTMLLinkElement>('link[rel=stylesheet]')).every(link => Boolean(link.sheet)))
  await page.evaluate(() => document.fonts.ready)
  const before = await page.locator('.dashboard-heading, [data-metric], .dashboard-panels').evaluateAll(elements => elements.map(element => {
    const rect = element.getBoundingClientRect(); return { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
  }))
  const beforeRows = await page.locator('.dashboard-table tr').evaluateAll(rows => rows.slice(0, 2).map(row => [...row.children].map(cell => ({ height: cell.getBoundingClientRect().height, width: cell.getBoundingClientRect().width, padding: getComputedStyle(cell).padding, line: getComputedStyle(cell).lineHeight, font: getComputedStyle(cell).fontSize, text: cell.textContent }))))
  release()
  await expect(page.locator('#laundrix-dashboard')).toHaveAttribute('data-renderer', 'react')
  const after = await page.locator('.dashboard-heading, [data-metric], .dashboard-panels').evaluateAll(elements => elements.map(element => {
    const rect = element.getBoundingClientRect(); return { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
  }))
  const afterRows = await page.locator('.dashboard-table tr').evaluateAll(rows => rows.slice(0, 2).map(row => [...row.children].map(cell => ({ height: cell.getBoundingClientRect().height, width: cell.getBoundingClientRect().width, padding: getComputedStyle(cell).padding, line: getComputedStyle(cell).lineHeight, font: getComputedStyle(cell).fontSize, text: cell.textContent }))))
  expect(afterRows).toEqual(beforeRows)
  expect(after).toEqual(before)
})

test('logout uses the real CSRF POST and ends the existing session', async ({ page }) => {
  await login(page, 'admin')
  const form = page.locator(`form[action='/auth/logout']`).filter({ visible: true })
  await expect(form).toHaveAttribute('method', 'post')
  const response = page.waitForResponse(response => response.url().endsWith('/auth/logout') && response.request().method() === 'POST')
  await form.getByRole('button', { name: 'Logout', exact: true }).click()
  expect((await response).status()).toBe(302)
  const dashboard = await page.request.get('/dashboard/', { maxRedirects: 0 })
  expect(dashboard.status()).toBe(302)
  expect(dashboard.headers().location).toContain('/auth/login')
})
