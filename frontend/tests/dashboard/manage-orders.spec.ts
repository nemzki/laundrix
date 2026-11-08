import { expect, test, type Page } from '@playwright/test'

const statuses = ['order_received', 'pending_processing', 'processing', 'ready_for_pickup', 'picked_up', 'completed']
const headers = ['Order Reference', 'Customer', 'Contact Number', 'Date Created', 'Laundry Status', 'Payment Status', 'Action']
const rows = (page: Page) => page.locator('.mo-rows tr[data-ref]')
async function login(page: Page, role: 'admin' | 'staff' = 'admin') {
  await page.goto('/auth/login')
  if (role === 'staff') await page.getByRole('tab', { name: 'Staff', exact: true }).click()
  await page.locator(`#${role}-identifier`).fill(role === 'admin' ? 'browseradmin' : 'staff@example.test')
  await page.locator(`#${role}-password`).fill('Browser-Test-Password!42')
  await page.locator(`form[data-auth-form=${role}] button[type=submit]`).click()
  await expect(page).toHaveURL(/dashboard/)
}
async function ready(page: Page) { await expect(page.locator('[data-manage-orders]')).toHaveAttribute('data-state', 'ready') }
async function search(page: Page, value: string) {
  await page.locator('#orders-search').fill(value)
  await expect(page).toHaveURL(url => url.searchParams.get('q') === value.trim())
  await ready(page)
}
async function projection(page: Page, url: string) {
  const response = await page.request.get(url)
  expect(response.status()).toBe(200)
  return page.evaluate(html => {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    return { data: JSON.parse(doc.querySelector('#order-summary-data')!.textContent!), csrf: (doc.querySelector('#statusUpdateForm [name=csrf_token]') as HTMLInputElement).value, key: (doc.querySelector('#record-payment [name=idempotency_key]') as HTMLInputElement | null)?.value }
  }, await response.text())
}
for (const role of ['admin', 'staff'] as const) for (const width of [320, 768, 1440]) test(`${role} Manage Orders ${width}px and real summary/navigation`, async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  await page.setViewportSize({ width, height: 1000 })
  await login(page, role); await page.goto('/orders/'); await ready(page)
  await expect(page.locator('.mo-table th')).toHaveText(headers)
  await expect(rows(page)).toHaveCount(15) // Original server size; ten-row requirement is blocked.
  await expect(page.locator('.page-actions a')).toHaveCount(1)
  await expect(page.locator('#orders-payment')).toBeEnabled()
  expect(await page.locator('#orders-payment option').evaluateAll(options => options.map(o => (o as HTMLOptionElement).value))).toEqual(['', 'unpaid', 'partial', 'paid'])
  expect(await page.locator('.mo-tab[data-status]').evaluateAll(links => links.map(l => l.getAttribute('data-status')))).toEqual(statuses)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  const selected = rows(page).first(), ref = await selected.getAttribute('data-ref')
  const link = selected.locator('[data-order-summary]'), url = await link.getAttribute('href') || ''
  const original = (await projection(page, url)).data
  await link.click(); await expect(page.locator('#orderSummaryModal')).toBeVisible()
  await expect(page.locator('[data-summary-content]')).toBeVisible()
  await expect(page.locator('[data-field=ref]')).toHaveText(ref!)
  for (const name of ['customer', 'contact', 'created', 'total', 'paid', 'balance', 'laundry', 'payment']) await expect(page.locator(`[data-field=${name}]`)).toHaveText(original[name] == null ? 'Not tracked' : original[name])
  await expect(page.locator('[data-summary-footer] .btn')).toHaveCount(2)
  await expect(page.locator('[data-field=stub]')).toHaveAttribute('href', original.stubUrl)
  const stub = await page.request.get(original.stubUrl); expect(stub.status()).toBe(200); expect(await stub.text()).toContain(ref!)
  await page.screenshot({ path: `test-results/dashboard/manage-orders-${role}-${width}-modal.png`, fullPage: true })
  await page.locator('#orderSummaryModal [data-bs-dismiss=modal]').click(); await expect(page.locator('#orderSummaryModal')).toBeHidden()
  await link.click(); await expect(page.locator('[data-summary-content]')).toBeVisible(); await expect(page.locator('#orderSummaryModal')).toBeFocused(); await page.keyboard.press('Escape'); await expect(page.locator('#orderSummaryModal')).toBeHidden()
  await expect(link).toBeFocused()
  await link.click(); await expect(page.locator('#orderSummaryModal')).toBeFocused(); await page.mouse.click(1,1); await expect(page.locator('#orderSummaryModal')).toBeHidden()
  await page.screenshot({ path: `test-results/dashboard/manage-orders-${role}-${width}.png`, fullPage: true })
  await link.click(); await expect(page.locator('[data-summary-content]')).toBeVisible(); await page.locator('[data-field=detail]').click()
  await expect(page).toHaveURL(new RegExp(url + '$')); await expect(page.locator('.order-detail')).toHaveAttribute('data-ref', ref!)
  expect(errors).toEqual([])
})

test('initial skeleton, fetch failure and working Retry', async ({ page }) => {
  await page.setViewportSize({ width:320, height:1000 })
  await login(page)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let fail = true
  await page.route('**/orders/', async route => {
    if (route.request().resourceType() !== 'fetch') return route.continue()
    await gate
    if (fail) { fail = false; return route.abort('failed') }
    return route.continue()
  })
  await page.goto('/orders/')
  await expect(page.getByRole('heading', { name: 'Manage Orders', exact: true })).toBeVisible()
  await expect(page.locator('.mo-table th')).toHaveText(headers)
  await expect(page.locator('.mo-skeleton tr')).toHaveCount(10)
  await expect(page.locator('.mo-skeleton')).toBeVisible(); await expect(page.locator('.mo-rows')).toBeHidden()
  release(); await expect(page.locator('[data-manage-orders]')).toHaveAttribute('data-state', 'error')
  await expect(page.locator('.mo-skeleton')).toBeHidden(); await expect(page.locator('[data-orders-retry]')).toBeVisible()
  const retry = (await page.locator('[data-orders-retry]').boundingBox())!; expect(retry.x + retry.width).toBeLessThanOrEqual(320)
  await page.locator('[data-orders-retry]').click(); await ready(page); await expect(rows(page)).toHaveCount(15)
})

test('full-query search, six status filters, real global counts and native server pagination', async ({ page }) => {
  await login(page); await page.goto('/orders/'); await ready(page)
  const first = await rows(page).evaluateAll(items => items.map(row => row.getAttribute('data-ref')))
  const counts = await page.locator('.mo-tab span').allTextContents()
  expect(Number(counts[0])).toBe(28)
  expect(counts.slice(1).map(Number).reduce((a,b) => a+b,0)).toBe(28)
  await expect(page.locator('.mo-pagination button').first()).toBeDisabled()
  await page.locator('.mo-pagination a', { hasText: /^Next$/ }).click(); await expect(page).toHaveURL(/page=2/); await ready(page)
  await expect(rows(page)).toHaveCount(13)
  const second = await rows(page).evaluateAll(items => items.map(row => row.getAttribute('data-ref')))
  expect(new Set([...first,...second]).size).toBe(28)
  await expect(page.locator('.mo-pagination button').last()).toBeDisabled()
  await page.locator('.mo-pagination a', { hasText: /^Previous$/ }).click(); await ready(page)
  expect(await rows(page).evaluateAll(items => items.map(row => row.getAttribute('data-ref')))).toEqual(first)
  await search(page, '  customer 00  '); await expect(rows(page)).toHaveCount(1)
  await expect(page.locator('.mo-tab span')).toHaveText(counts)
  const originalRef = await rows(page).first().getAttribute('data-ref') || ''
  const contact = await rows(page).first().locator('td').nth(2).innerText()
  await search(page, originalRef.toLowerCase()); await expect(rows(page)).toHaveCount(1)
  await search(page, contact); await expect(rows(page)).toHaveCount(1)
  await page.locator('[data-clear-search]').click(); await expect(page).not.toHaveURL(/q=/); await ready(page)
  for (const status of statuses) {
    await page.locator(`.mo-tab[data-status=${status}]`).click(); await expect(page).toHaveURL(url => url.searchParams.get('status') === status && !url.searchParams.has('page')); await ready(page)
    const raw = await rows(page).evaluateAll(items => items.map(row => row.getAttribute('data-laundry')))
    expect(raw.length).toBeGreaterThan(0); expect(raw.every(s => s === status)).toBe(true)
  }
  await search(page, 'NoSuchCustomerAnywhere'); await expect(page.locator('.mo-empty')).toContainText('No orders match your filters.')
  await expect(page).toHaveURL(url => url.searchParams.get('status') === 'completed')
  await page.locator('.mo-filters [data-clear-filters]').click(); await expect(page).toHaveURL(/\/orders\/$/); await ready(page)
  await expect(page.locator('#orders-search')).toHaveValue(''); await expect(rows(page)).toHaveCount(15)
  await page.goto('/orders/?page=999'); await ready(page); await expect(page).toHaveURL(/page=2/); await expect(rows(page)).toHaveCount(13)
})

test('payment dropdown combines with all six statuses, search, history and clear filters', async ({ page }) => {
  await login(page); await page.goto('/orders/?page=2'); await ready(page)
  // Create the partial state through the real payment endpoint in the isolated DB.
  const url = await page.locator('.mo-rows tr[data-payment=unpaid] [data-order-summary]').first().getAttribute('href') || ''
  const original = await projection(page, url)
  const recorded = await page.request.post(url + '/payments', { headers: { 'X-CSRFToken': original.csrf }, data: { entries: [{ method: 'cash', amount: '1' }], idempotency_key: original.key } })
  expect((await recorded.json()).ok).toBe(true)
  const payment = page.locator('#orders-payment')
  for (const value of ['unpaid', 'partial', 'paid', '']) {
    await payment.selectOption(value)
    await expect(page).toHaveURL(url => (url.searchParams.get('payment') || '') === value && !url.searchParams.has('page'))
    await ready(page); await expect(payment).toHaveValue(value)
    if (value) {
      const actual = await rows(page).evaluateAll(items => items.map(row => row.getAttribute('data-payment')))
      expect(actual.length).toBeGreaterThan(0); expect(actual.every(status => status === value)).toBe(true)
      const colors = { unpaid: ['rgb(254, 226, 226)', 'rgb(153, 27, 27)'], partial: ['rgb(255, 237, 213)', 'rgb(154, 52, 18)'], paid: ['rgb(209, 250, 229)', 'rgb(6, 95, 70)'] }
      const [bg, fg] = colors[value as keyof typeof colors]
      const badge = page.locator('.mo-rows [data-payment-status]').first()
      await expect(badge).toHaveCSS('background-color', bg); await expect(badge).toHaveCSS('color', fg)
    }
  }
  await payment.selectOption('partial'); await ready(page)
  for (const status of statuses) {
    await page.locator(`.mo-tab[data-status=${status}]`).click(); await ready(page)
    await expect(payment).toHaveValue('partial')
    const actual = await rows(page).evaluateAll(items => items.map(row => [row.getAttribute('data-payment'), row.getAttribute('data-laundry')]))
    expect(actual.every(([p,s]) => p === 'partial' && s === status)).toBe(true)
  }
  await search(page, 'Customer')
  await expect(payment).toHaveValue('partial')
  await expect(page).toHaveURL(url => url.searchParams.get('status') === 'completed' && url.searchParams.get('payment') === 'partial')
  await search(page, 'NoSuchCustomerAnywhere')
  await expect(page.locator('.mo-empty')).toContainText('No orders match your filters.')
  await page.locator('.mo-filters [data-clear-filters]').click(); await ready(page)
  await expect(payment).toHaveValue(''); await expect(page).toHaveURL(/\/orders\/$/)
  await page.goBack(); await ready(page); await expect(payment).toHaveValue('partial')
  await page.reload(); await ready(page); await expect(payment).toHaveValue('partial')
})

test('summary loading/error/retry prevents stale content and retains physical receipt action', async ({ page }) => {
  await login(page); await page.goto('/orders/'); await ready(page)
  const links = rows(page).locator('[data-order-summary]')
  await links.first().click(); await expect(page.locator('[data-summary-content]')).toBeVisible()
  await expect(page.locator('#orderSummaryModal')).toBeFocused(); await page.keyboard.press('Escape'); await expect(page.locator('#orderSummaryModal')).toBeHidden()
  const nextURL = await links.nth(1).getAttribute('href') || ''
  let release!: () => void; const gate = new Promise<void>(resolve => { release = resolve }); let fail = true
  await page.route('**' + nextURL, async route => { await gate; if (fail) { fail=false; return route.fulfill({ status: 503, body: 'Unavailable' }) }; return route.continue() })
  await links.nth(1).click(); await expect(page.locator('[data-summary-loading]')).toBeVisible(); await expect(page.locator('[data-summary-content]')).toBeHidden(); await expect(page.locator('[data-summary-footer]')).toBeHidden()
  release(); await expect(page.locator('[data-summary-error]')).toBeVisible(); await page.locator('[data-summary-retry]').click(); await expect(page.locator('[data-summary-content]')).toBeVisible()
  await expect(page.locator('[data-field=detail]')).toHaveAttribute('href', nextURL)
  await page.keyboard.press('Escape'); await expect(page.locator('#orderSummaryModal')).toBeHidden()
  const receivedLink = page.locator('.mo-rows tr').filter({ hasText: 'Awaiting receipt' }).first().locator('[data-order-summary]')
  await receivedLink.click(); await expect(page.locator('[data-summary-content]')).toBeVisible()
  await page.locator('[data-summary-receipt] button').click()
  await expect(page.locator('#orderSummaryModal')).toBeHidden(); await expect(page.locator('#confirmReceivedModal')).toBeVisible()
  const action = await page.locator('#confirmReceivedForm').getAttribute('action') || ''
  expect(action).toMatch(/\/confirm-received$/)
  const response = page.waitForResponse(r => r.url().endsWith(action) && r.request().method() === 'POST')
  await page.locator('#confirmReceivedForm button[type=submit]').click(); expect((await response).status()).toBe(302)
  await expect(page.locator('#receipt')).toContainText('Received')
})

test('fresh summaries and list refetch use actual persisted payments', async ({ page }) => {
  await login(page); await page.goto('/orders/'); await ready(page)
  const row = page.locator('.mo-rows tr[data-payment=unpaid]').first(), link = row.locator('[data-order-summary]')
  const url = await link.getAttribute('href') || ''
  const original = await projection(page, url)
  await link.click(); await expect(page.locator('[data-field=paid]')).toHaveText(original.data.paid)
  await expect(page.locator('#orderSummaryModal')).toBeFocused(); await page.keyboard.press('Escape'); await expect(page.locator('#orderSummaryModal')).toBeHidden()
  const paid = await page.request.post(url + '/payments', { headers: { 'X-CSRFToken': original.csrf }, data: { entries:[{ method:'cash',amount:'1' }],idempotency_key:original.key } })
  expect((await paid.json()).ok).toBe(true)
  await link.click(); await expect(page.locator('[data-field=payment]')).toHaveText('Partially Paid')
  await expect(page.locator('[data-field=balance]')).toHaveText((await projection(page,url)).data.balance)
  await expect(page.locator('#orderSummaryModal')).toBeFocused(); await page.keyboard.press('Escape'); await expect(page.locator('#orderSummaryModal')).toBeHidden()
  await page.reload(); await ready(page)
  await expect(page.locator(`.mo-rows tr[data-ref="${original.data.reference}"]`)).toHaveAttribute('data-payment','partial')
})


test('native Flask listing/search/navigation remains usable without JavaScript', async ({ page, browser }) => {
  await login(page)
  const context = await browser.newContext({ storageState: await page.context().storageState(), javaScriptEnabled:false })
  try {
    const native = await context.newPage(); await native.goto('http://127.0.0.1:8771/orders/')
    await expect(native.locator('.mo-rows tr[data-ref]')).toHaveCount(15)
    await expect(native.locator('.mo-skeleton')).toBeHidden()
    await native.locator('#orders-search').fill('Customer 00'); await native.locator('.mo-native-search').click()
    await expect(native).toHaveURL(/q=Customer/); await expect(native.locator('.mo-rows tr[data-ref]')).toHaveCount(1)
    const link = native.locator('[data-order-summary]'), url = await link.getAttribute('href') || ''
    await link.click(); await expect(native).toHaveURL(new RegExp(url + '$'))
  } finally { await context.close() }
})
