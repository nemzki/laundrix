import { expect, test, type Page } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const violations: string[] = []
    Object.assign(window, { cspViolations: violations })
    document.addEventListener('securitypolicyviolation', event => violations.push(`${event.effectiveDirective}: ${event.blockedURI}`))
  })
})

async function login(page: Page) {
  await page.goto('/auth/login')
  await page.getByLabel('Email or Username').fill('browseradmin')
  await page.locator('#admin-password').fill('Browser-Test-Password!42')
  await page.locator('form[data-auth-form=admin] button[type=submit]').click()
  await expect(page).toHaveURL(/dashboard/)
  await page.goto('/orders/')
  await expect(page.locator('#laundrix-react-orders')).toHaveAttribute('data-ready', 'true')
}

test('React mounts through Flask; summary uses each selected order and closes accessibly', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await login(page)
  await expect(page.locator('[data-orders-jinja]')).toBeHidden()
  const data = await page.locator('#laundrix-orders-data').textContent().then(text => JSON.parse(text!))
  for (const [index, order] of data.orders.slice(0, 4).entries()) {
    const view = page.getByRole('button', { name: `View order ${order.reference}`, exact: true }).filter({ visible: true })
    await view.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toHaveCount(1)
    expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).toBe('hidden')
    for (let i = 0; i < 5; i++) {
      await page.keyboard.press('Tab')
      expect(await page.evaluate(() => Boolean(document.activeElement?.closest('[role=dialog]')))).toBe(true)
    }
    await expect(dialog.locator('[data-order-summary-reference]')).toHaveAttribute('data-order-summary-reference', order.reference)
    for (const text of [order.customer, order.contact, order.created, order.total, order.paid, order.balance, order.laundry, order.payment]) {
      await expect(dialog.getByText(text, { exact: true }).first()).toBeVisible()
    }
    await expect(dialog.getByRole('link', { name: 'Print Stub' })).toHaveAttribute('href', order.stubUrl)
    await expect(dialog.getByRole('link', { name: 'Open Full Order' })).toHaveAttribute('href', order.detailUrl)
    if (index % 3 === 0) await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    else if (index % 3 === 1) await page.keyboard.press('Escape')
    else await page.locator('[data-slot=dialog-overlay]').click({ position: { x: 5, y: 5 } })
    await expect(dialog).toHaveCount(0)
    await expect(view).toBeFocused()
    expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).not.toBe('hidden')
  }
  expect(errors).toEqual([])
  expect(await page.evaluate(() => (window as unknown as { cspViolations: string[] }).cspViolations)).toEqual([])
})

test('native GET search, status tabs and pagination preserve the selected filter', async ({ page }) => {
  await login(page)
  const root = page.locator('#laundrix-react-orders')
  await root.getByRole('link', { name: 'Next', exact: true }).click()
  await expect(page).toHaveURL(/page=2/)
  await expect(root).toHaveAttribute('data-ready', 'true')
  await root.getByLabel('Search orders').fill('definitely-missing')
  await root.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(page).toHaveURL(/q=definitely-missing/)
  await expect(root.getByText('No matching orders')).toBeVisible()
  await root.getByRole('link', { name: 'Clear', exact: true }).click()
  await expect(root.getByRole('combobox')).toHaveCount(0)
  await root.getByRole('tab', { name: /^Processing/ }).click()
  await expect(page).toHaveURL(/status=processing/)
  await root.getByLabel('Search orders').fill('definitely-missing')
  await root.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(page).toHaveURL(/status=processing/)
  await expect(page).toHaveURL(/q=definitely-missing/)
  await expect(root.getByText('No matching orders')).toBeVisible()
  await root.getByRole('link', { name: 'Clear', exact: true }).click()
  await root.getByRole('tab', { name: /^All orders/ }).click()
  await expect(page).toHaveURL(/\/orders\/$/)
})

test('stub opens correct Flask receipt, print invokes once, full order navigation works', async ({ page }) => {
  await login(page)
  await page.getByRole('button', { name: /^View order/ }).filter({ visible: true }).first().click()
  const dialog = page.getByRole('dialog')
  const reference = await dialog.locator('[data-order-summary-reference]').getAttribute('data-order-summary-reference')
  const popupPromise = page.waitForEvent('popup')
  await dialog.getByRole('link', { name: 'Print Stub' }).click()
  const stub = await popupPromise
  await expect(stub.locator('.stub-reference')).toHaveText(reference!)
  await stub.evaluate(() => { (window as unknown as { printCalls: number }).printCalls = 0; window.print = () => { (window as unknown as { printCalls: number }).printCalls++ } })
  await stub.locator('[data-print]').click()
  expect(await stub.evaluate(() => (window as unknown as { printCalls: number }).printCalls)).toBe(1)
  await stub.emulateMedia({ media: 'print' })
  await expect(stub.locator('.stub-toolbar')).toBeHidden()
  await expect(stub.locator('.stub-logo')).toBeVisible()
  await stub.close()
  await dialog.getByRole('link', { name: 'Open Full Order' }).click()
  await expect(page).toHaveURL(new RegExp(`/orders/${reference}$`))
  await expect(page.locator('.order-detail')).toHaveAttribute('data-ref', reference!)
})

test('Jinja rollback, unavailable bundle and disabled JavaScript retain working controls', async ({ page, browser }) => {
  await login(page)
  const shellStyle = () => page.locator('.lx-sidebar').evaluate(element => {
    const style = getComputedStyle(element)
    return [style.width, style.fontFamily, style.backgroundColor, style.color]
  })
  const reactShell = await shellStyle()
  await page.goto('/orders/?ui=jinja')
  expect(await shellStyle()).toEqual(reactShell)
  await expect(page.locator('#laundrix-react-orders')).toHaveCount(0)
  await expect(page.locator('[data-orders-filters]')).toBeVisible()
  await page.route('**/react/orders.js', route => route.abort())
  await page.goto('/orders/', { waitUntil: 'commit' })
  await expect(page.locator('#laundrix-react-orders')).toHaveAttribute('data-renderer', 'server')
  await expect(page.locator('#laundrix-react-orders')).toBeVisible()
  await expect(page.locator('[data-orders-jinja]')).toBeHidden()
  const context = await browser.newContext({ javaScriptEnabled: false, storageState: await page.context().storageState() })
  const noJS = await context.newPage()
  await noJS.goto('/orders/', { waitUntil: 'commit' })
  await expect(noJS.locator('[data-orders-filters]').filter({ visible: true })).toBeVisible()
  await context.close()
  const cssContext = await browser.newContext({ storageState: await page.context().storageState() })
  const noCSS = await cssContext.newPage()
  await noCSS.route('**/react/orders.css', route => route.abort())
  await noCSS.goto('/orders/', { waitUntil: 'commit' })
  await expect(noCSS.locator('[data-orders-jinja]')).toBeVisible()
  await expect(noCSS.locator('#laundrix-react-orders')).toBeHidden()
  await cssContext.close()
})

test('CSRF is enforced for existing mutation routes', async ({ page }) => {
  await login(page)
  const response = await page.request.post('/orders/new/confirm', { data: {} })
  expect(response.status()).toBe(400)
})

for (const width of [320, 768, 1440]) {
  test(`React page and dialog fit ${width}px without document overflow`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await login(page)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: `test-results/orders-table-${width}.png` })
    await page.getByRole('button', { name: /^View order/ }).filter({ visible: true }).first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('link', { name: 'Print Stub' })).toBeInViewport()
    await expect(dialog.getByRole('link', { name: 'Open Full Order' })).toBeInViewport()
    const box = await dialog.boundingBox()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1)
    await page.screenshot({ path: `test-results/orders-dialog-${width}.png` })
  })
}

test('seven-column density, long content and all statuses fit desktop, tablet and mobile', async ({ page }) => {
  // Layout stress fixtures extend an authorized Flask response; workflow tests above use real data.
  await page.route('**/orders/', async route => {
    const response = await route.fetch()
    const html = (await response.text()).replace(
      /(<script type="application\/json" id="laundrix-orders-data">)([\s\S]*?)(<\/script>)/,
      (_match, start, json, end) => {
        const data = JSON.parse(json)
        data.orders[0].customer = 'Li'
        data.orders[0].total = '₱99,999,999.99'
        data.orders[0].balanceNote = '₱99,999,999.99'
        data.orders[1].customer = 'Maria Alexandra '.repeat(10).trim()
        return start + JSON.stringify(data).replace(/</g, '\\u003c') + end
      },
    )
    await route.fulfill({ response, body: html })
  })
  await login(page)
  const root = page.locator('#laundrix-react-orders')
  for (const width of [320, 768, 1024, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await expect(root.getByRole('tab')).toHaveCount(7)
    if (width >= 768) {
      const table = root.getByRole('table')
      await expect(table.getByRole('columnheader')).toHaveText(['Order Reference', 'Customer', 'Contact Number', 'Date Created', 'Laundry Status', 'Payment Status', 'Action'])
      const measurements = await table.evaluate(element => {
        const table = element as HTMLTableElement
        const rows = [...table.tBodies[0].rows]
        return {
          fits: table.scrollWidth <= table.parentElement!.clientWidth + 1 || innerWidth < 1280,
          naturalHeight: table.parentElement!.scrollHeight <= table.parentElement!.clientHeight + 1,
          normalHeights: rows.slice(2).map(row => row.getBoundingClientRect().height),
          cellsFit: rows.every(row => [...row.cells].every(cell => cell.scrollWidth <= cell.clientWidth + 1)),
          actions: rows.every(row => row.cells[6].querySelectorAll('button').length === 1),
          statusCount: new Set(rows.map(row => row.cells[4].querySelector('[data-slot=badge]')!.textContent)).size,
        }
      })
      expect(measurements.fits).toBe(true)
      expect(measurements.naturalHeight).toBe(true)
      expect(measurements.cellsFit).toBe(true)
      expect(measurements.actions).toBe(true)
      expect(measurements.statusCount).toBe(6)
      // Tablet can wrap compact secondary data; ordinary desktop rows stay within the density target.
      if (width >= 1280) expect(measurements.normalHeights.every(height => height >= 64 && height <= 76)).toBe(true)
    } else {
      await expect(root.locator('.mo-mobile-orders')).toBeVisible()
      await expect(root.locator('.mo-mobile-orders article').first().getByRole('button', { name: /^View order/ })).toBeVisible()
    }
    await page.screenshot({ path: `test-results/orders-stress-${width}.png` })
  }
})
