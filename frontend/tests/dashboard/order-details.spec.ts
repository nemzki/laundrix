import { expect, test, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'

const values = ['order_received', 'pending_processing', 'processing', 'ready_for_pickup', 'picked_up', 'completed']
const labels = ['Order Received', 'Pending Processing', 'Processing', 'Ready for Pickup', 'Picked Up / Released', 'Completed']
const money = (amount: number) => `₱${amount.toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

async function login(page: Page, role: 'admin' | 'staff') {
  await page.goto('/auth/login')
  if (role === 'staff') await page.getByRole('tab', { name: 'Staff', exact: true }).click()
  await page.locator(`#${role}-identifier`).fill(role === 'admin' ? 'browseradmin' : 'staff@example.test')
  await page.locator(`#${role}-password`).fill('Browser-Test-Password!42')
  await page.locator(`form[data-auth-form=${role}] button[type=submit]`).click()
  await expect(page).toHaveURL(/dashboard/)
}

async function create(page: Page) {
  await page.goto('/orders/new')
  const csrf = await page.locator('#wizard').getAttribute('data-csrf') || ''
  const token = await page.locator('#wizard').getAttribute('data-token')
  const spin = await page.locator('input[data-code=spin]').getAttribute('data-id')
  const pkg = page.locator('input[data-kind=package]').first()
  const packageId = await pkg.getAttribute('data-id')
  const measurement = await pkg.getAttribute('data-min')
  const extras = await page.locator('[data-extra]').evaluateAll(items => items.filter(item => (item as HTMLElement).dataset.chargeable === '1' && (item as HTMLElement).dataset.supplied === '1').map(item => ({ id: (item as HTMLElement).dataset.id })))
  const customer = (await (await page.request.get('/orders/customers/search?q=Customer%2000')).json()).results[0]
  const payload = {
    submission_token: token, require_customer: true, customer: { id: customer.id }, sms_consent: true,
    items: [{ kind: 'service', id: spin, quantity: '1', instructions: 'Historical service instructions' }, { kind: 'package', id: packageId, quantity: '1', measurement }],
    extras: extras.map((extra, index) => ({ id: extra.id, mode: index === 0 ? 'paid' : 'customer_supplied', quantity: index === 0 ? '2' : '1' })),
    notes: 'Preserve order handling instructions',
    payment: { arrangement: 'partial', entries: [{ method: 'cash', amount: '30', notes: 'Cash collection note' }, { method: 'gcash', amount: '10', reference: 'DetailsReference123', notes: 'GCash collection note' }] },
  }
  const quote = await (await page.request.post('/orders/new/quote', { headers: { 'X-CSRFToken': csrf }, data: payload })).json()
  expect(quote.ok).toBe(true)
  const saved = await (await page.request.post('/orders/new/confirm', { headers: { 'X-CSRFToken': csrf }, data: payload })).json()
  expect(saved.ok).toBe(true)
  const detailURL = saved.redirect.replace(/\/confirmation$/, '')
  await page.goto(detailURL)
  return { csrf, quote, detailURL }
}

async function checkQR(page: Page) {
  const qr = page.locator('[data-tracking-image]')
  await expect(qr).toBeVisible()
  const original = await page.request.get(await page.locator('[data-order-tracking]').getAttribute('data-stub-url') || '')
  const html = await original.text()
  const source = html.match(/<img src="(data:image\/png;base64,[^"]+)" alt="QR code for tracking order/)?.[1]
  expect(source).toBeTruthy()
  await expect(qr).toHaveAttribute('src', source || '')
  expect(await qr.evaluate(img => getComputedStyle(img).objectFit)).toBe('contain')
  const link = await page.locator('#order-tracking-link').inputValue()
  const publicPage = await page.request.get(new URL(link).pathname)
  expect(publicPage.status()).toBe(200)
  expect(await publicPage.text()).toContain(await page.locator('.order-detail').getAttribute('data-ref'))
  return link
}

async function submitForm(page: Page, selector: string, endpoint: string) {
  const response = page.waitForResponse(r => r.url().endsWith(endpoint) && r.request().method() === 'POST')
  // Payment saves use fetch followed by a reload; waiting on the old document's load state races that reload.
  const navigation = page.waitForEvent('framenavigated', frame => frame === page.mainFrame())
  await page.locator(selector).locator('button[type=submit]').click()
  expect((await response).status()).toBe(endpoint.endsWith('/payments') ? 200 : 302)
  await navigation
  await page.waitForLoadState('domcontentloaded')
}

async function status(page: Page, value: string, note?: string) {
  await page.locator(`[data-status-update][data-status="${value}"]`).click()
  await expect(page.locator('#statusUpdateModal')).toBeVisible()
  if (note) await page.locator('#statusUpdateNote').fill(note)
  const action = await page.locator('#statusUpdateForm').getAttribute('action') || ''
  await submitForm(page, '#statusUpdateForm', action)
  await expect(page.locator('#statusUpdateModal')).toBeHidden()
  await expect(page.locator('.order-tracker__step[aria-current=step]')).toHaveAttribute('data-workflow-status', value)
}

for (const role of ['admin', 'staff'] as const) for (const width of [320, 768, 1440]) {
  test(`${role} Order Details layout/data/QR parity at ${width}px`, async ({ page, context }) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.setViewportSize({ width, height: 1000 })
    await login(page, role)
    const { quote } = await create(page)
    await expect(page.locator('.order-tracker__label')).toHaveText(labels)
    expect(await page.locator('[data-workflow-status]').evaluateAll(items => items.map(item => item.getAttribute('data-workflow-status')))).toEqual(values)
    await expect(page.locator('.order-tracker__step[aria-current=step]')).toHaveAttribute('data-workflow-status', 'order_received')
    const main = page.locator('.order-detail__main'), side = page.locator('.order-detail__side')
    await expect(main.getByRole('heading', { name: 'Laundry Status', exact: true })).toBeVisible()
    await expect(main.getByRole('heading', { name: 'Laundry Services', exact: true })).toBeVisible()
    await expect(main.getByRole('heading', { name: 'Payment Information', exact: true })).toBeVisible()
    await expect(main.getByRole('heading', { name: 'Order Activity', exact: true })).toBeVisible()
    for (const name of ['Order Information', 'Customer Information', 'SMS Notification', 'QR Tracking']) await expect(side.getByRole('heading', { name, exact: true })).toBeVisible()
    for (const line of quote.lines) await expect(main).toContainText(line.name)
    await expect(main).toContainText('Historical service instructions')
    await expect(side).toContainText('Preserve order handling instructions')
    await expect(page.locator('#payment .order-detail__finance dd')).toHaveText([quote.total, quote.payment.received, quote.payment.balance])
    await expect(page.locator('.pay-txn')).toHaveCount(2)
    await expect(page.locator('#payment')).toContainText('DetailsReference123')
    await expect(page.locator('#payment')).toContainText('GCash collection note')
    await expect(page.locator('[data-confirm-received]')).toHaveCount(1)
    await expect(page.locator('[data-status-update]')).toHaveCount(0)
    await expect(page.locator('#sms')).toContainText('Yes')
    await expect(page.locator('[data-reverse-payment]')).toHaveCount(role === 'admin' ? 2 : 0)
    await expect(page.locator('iframe')).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Printable Order Stub', exact: true })).toHaveCount(0)
    const tracking = await checkQR(page)
    await page.getByRole('button', { name: 'Copy Tracking Link', exact: true }).click()
    await expect(page.locator('[data-copy-status]')).toHaveText('Tracking link copied.')
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(tracking)
    const print = page.getByRole('link', { name: 'Print Stub', exact: true })
    expect((await page.request.get(await print.getAttribute('href') || '')).status()).toBe(200)
    await expect(print).toHaveAttribute('target', '_blank')
    await expect(page.locator('#record-payment')).toBeHidden()
    await page.locator('[data-bs-target="#recordPaymentModal"]').click()
    await expect(page.locator('#record-payment')).toBeVisible()
    await expect(page.locator('#pa-1')).toHaveValue((Number(quote.total_raw) - 40).toFixed(2))
    await page.locator('[data-method=gcash]').click()
    await expect(page.locator('[data-payment-gcash]')).toBeVisible()
    await expect(page.locator('#pr-1')).toHaveAttribute('required', '')
    const paymentFooter = (await page.locator('#recordPaymentModal .modal-footer').boundingBox())!
    expect(paymentFooter.y + paymentFooter.height).toBeLessThanOrEqual(1000)
    await page.locator('[data-method=cash]').click()
    await page.locator('#recordPaymentModal [data-bs-dismiss=modal]').first().click()
    await expect(page.locator('#recordPaymentModal')).toBeHidden()
    const left = (await main.boundingBox())!, right = (await side.boundingBox())!
    if (width === 1440) {
      expect(right.x).toBeGreaterThan(left.x + left.width)
      expect(Math.abs((right.x - left.x - left.width) - 20)).toBeLessThan(1)
      expect(left.width / (left.width + right.width)).toBeCloseTo(.69, 2)
    } else expect(right.y).toBeGreaterThan(left.y)
    for (const label of await page.locator('.order-tracker__label').all()) expect(await label.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }))
    await page.screenshot({ path: `test-results/dashboard/order-details-${role}-${width}.png`, fullPage: true })
    expect(errors).toEqual([])
  })
}

for (const role of ['admin', 'staff'] as const) test(`${role} original receipt/status/payment/reversal workflow stays functional`, async ({ page }) => {
  test.setTimeout(90000)
  await login(page, role)
  const { quote, detailURL } = await create(page)
  await page.locator('[data-confirm-received]').click()
  await expect(page.locator('#confirmReceivedModal')).toBeVisible()
  await submitForm(page, '#confirmReceivedForm', `${detailURL}/confirm-received`)
  await expect(page.locator('#confirmReceivedModal')).toBeHidden()
  await expect(page.locator('#receipt')).toContainText('Received')
  for (const value of ['pending_processing', 'processing', 'ready_for_pickup']) await status(page, value)
  await expect(page.locator('.order-detail__timeline li strong').first()).toHaveText('Ready for Pickup')
  const dark = await page.locator('html').getAttribute('data-lx-theme') === 'dark'
  expect(await page.locator('.order-tracker__step.is-done .order-tracker__marker').first().evaluate(el => getComputedStyle(el).backgroundColor)).toBe(dark ? 'rgb(21, 51, 70)' : 'rgb(224, 242, 254)')
  await expect(page.locator('#sms .status')).toHaveText('Pending')
  await expect(page.locator('#sms')).toContainText('SMS is disabled. Nothing has been sent')
  await expect(page.locator('[data-sms-retry]')).toHaveCount(0)
  await expect(page.locator('#payment .order-detail__finance dd').nth(1)).toHaveText(quote.payment.received)
  await page.locator('[data-status-update][data-status=picked_up]').click()
  await expect(page.locator('[data-toast-title]')).toHaveText('Settle the remaining balance first')
  await expect(page.locator('#statusUpdateModal')).toBeHidden()
  await expect(page.locator('.order-tracker__step[aria-current=step]')).toHaveAttribute('data-workflow-status', 'ready_for_pickup')
  await page.locator('[data-toast-close]').click()
  await page.locator('[data-bs-target="#recordPaymentModal"]').click()
  await page.locator('#pa-1').fill(String(Number(quote.total_raw) + 1))
  await page.locator('#record-payment button[type=submit]').click()
  expect(await page.locator('#pa-1').evaluate((el: HTMLInputElement) => el.validity.rangeOverflow)).toBe(true)
  await expect(page.locator('.pay-txn')).toHaveCount(2)
  await page.locator('[data-method=cash]').click(); await page.locator('#pa-1').fill('20')
  await page.locator('#record-payment details > summary').click()
  await page.locator('#pm-2').selectOption('gcash'); await page.locator('#pa-2').fill('10')
  await page.locator('#pr-2').fill('LaterReference123'); await page.locator('#pn').fill('Later split collection')
  await submitForm(page, '#record-payment', `${detailURL}/payments`)
  await expect(page.locator('.pay-txn')).toHaveCount(4)
  let paid = 70
  await expect(page.locator('#payment .order-detail__finance dd').nth(1)).toHaveText(money(paid))
  if (role === 'admin') {
    const reverse = page.locator('[data-reverse-payment]').first()
    const amount = Number((await reverse.getAttribute('data-amount') || '').replace(/[^\d.]/g, ''))
    const action = await reverse.getAttribute('data-action') || ''
    await reverse.click(); await expect(page.locator('#reversePaymentModal')).toBeVisible()
    await page.locator('#reverseReason').fill('Correcting a duplicated collection entry')
    await submitForm(page, '#reversePaymentForm', action)
    await expect(page.locator('#reversePaymentModal')).toBeHidden()
    paid -= amount
    await expect(page.locator('#payment .order-detail__finance dd').nth(1)).toHaveText(money(paid))
    await expect(page.locator('.pay-txn')).toHaveCount(5)
  } else await expect(page.locator('[data-reverse-payment]')).toHaveCount(0)
  const remaining = Number(quote.total_raw) - paid
  await page.locator('[data-bs-target="#recordPaymentModal"]').click()
  await page.locator('[data-method=cash]').click(); await page.locator('#pa-1').fill(String(remaining))
  await submitForm(page, '#record-payment', `${detailURL}/payments`)
  await expect(page.locator('#payment .order-detail__finance dd').last()).toHaveText('₱0.00')
  await expect(page.locator('#record-payment')).toHaveCount(0)
  await expect(page.locator('.page-actions a[href="#record-payment"]')).toHaveCount(0)
  for (const value of ['picked_up', 'completed']) await status(page, value)
  await expect(page.locator('#payment .status')).toHaveText('Paid')
  if (role === 'admin') {
    await status(page, 'picked_up', 'Correcting premature completion')
    await expect(page.locator('.order-detail__timeline li').first()).toContainText('Correcting premature completion')
  } else await expect(page.locator('[data-status-update]')).toHaveCount(0)
  await checkQR(page)
})


test('configured GCash modal, real server validation, split payment and settings refresh', async ({ page }) => {
  test.setTimeout(90000)
  await login(page, 'admin')
  const { detailURL } = await create(page)
  const csrf = await page.locator('#record-payment input[name=csrf_token]').inputValue()
  const headers = { 'X-CSRFToken': csrf }
  await page.locator('[data-bs-target="#recordPaymentModal"]').click()
  await page.locator('[data-method=gcash]').click()
  await expect(page.locator('#pr-1')).toHaveAttribute('required', '')
  await page.locator('#record-payment button[type=submit]').click()
  expect(await page.locator('#pr-1').evaluate((el: HTMLInputElement) => el.validity.valueMissing)).toBe(true)
  await expect(page.locator('.pay-txn')).toHaveCount(2)
  await page.locator('#pr-1').fill('   ')
  expect(await page.locator('#pr-1').evaluate((el: HTMLInputElement) => el.validity.customError)).toBe(true)
  await expect(page.locator('[data-payment-config-status]')).toContainText('GCash QR code is not configured. Please check Payment Settings.')
  await expect(page.locator('[data-payment-qr]')).toBeHidden()
  await page.locator('#recordPaymentModal [data-bs-dismiss=modal]').first().click()
  const settings = await page.request.post('/payments/settings', { headers, data: { partial_enabled: true, pay_later_enabled: true, gcash_account_name: 'Isolated QA Recipient', gcash_account_number: '09170000000', payment_instructions: 'Verify the isolated QA recipient.' } })
  expect(settings.status()).toBe(200)
  // A non-payment test image, uploaded only into the isolated fixture's temporary directory.
  const png = execFileSync('../.venv/Scripts/python.exe', ['-c', 'import io,sys; from PIL import Image; b=io.BytesIO(); Image.new("RGB",(160,160),"blue").save(b,"PNG"); sys.stdout.buffer.write(b.getvalue())'])
  const upload = await page.request.post('/payments/settings/qr', { headers, multipart: { image: { name: 'isolated-qa-image.png', mimeType: 'image/png', buffer: png } } })
  expect(upload.status()).toBe(200)
  await page.locator('[data-bs-target="#recordPaymentModal"]').click()
  await expect(page.locator('[data-payment-account]')).toContainText('Isolated QA Recipient')
  await expect(page.locator('[data-payment-account]')).toContainText('09170000000')
  await expect(page.locator('[data-payment-qr]')).toBeVisible()
  const footer = (await page.locator('#recordPaymentModal .modal-footer').boundingBox())!
  expect(footer.y + footer.height).toBeLessThanOrEqual(page.viewportSize()!.height)
  await page.screenshot({ path: 'test-results/dashboard/order-details-payment-modal.png', fullPage: true })
  await expect(page.locator('[data-payment-qr]')).toHaveAttribute('src', /\/payments\/qr$/)
  expect(await page.locator('[data-payment-qr]').evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(160)
  await page.locator('#pr-1').fill('invalid@reference')
  const rejected = page.waitForResponse(r => r.url().endsWith(`${detailURL}/payments`) && r.request().method() === 'POST')
  await page.locator('#record-payment button[type=submit]').click()
  expect((await rejected).status()).toBe(422)
  await expect(page.locator('[data-payment-errors]')).toContainText('reference may only contain')
  await expect(page.locator('#recordPaymentModal')).toBeVisible()
  await expect(page.locator('#pr-1')).toHaveValue('invalid@reference')
  await expect(page.locator('.pay-txn')).toHaveCount(2)
  await page.locator('[data-method=cash]').click()
  await expect(page.locator('[data-payment-gcash]')).toBeHidden()
  await page.locator('#pr-1').fill('')
  await page.locator('#record-payment details > summary').click()
  await page.locator('#pm-2').selectOption('cash')
  expect(await page.locator('#pm-2').evaluate((el: HTMLSelectElement) => el.validity.customError)).toBe(true)
  await page.locator('#pm-2').selectOption('gcash')
  await expect(page.locator('#pr-2')).toHaveAttribute('required', '')
  await page.locator('#pa-1').fill('120'); await page.locator('#pa-2').fill('100')
  expect(await page.locator('#pa-1').evaluate((el: HTMLInputElement) => el.validity.customError)).toBe(true)
  await page.locator('#pa-1').fill('100'); await page.locator('#pr-2').fill('VerifiedReference123')
  await expect(page.locator('[data-payment-gcash]')).toBeVisible()
  await expect(page.locator('[data-payment-preview]')).toContainText('Total to record:')
  const sent = page.waitForRequest(r => r.url().endsWith(`${detailURL}/payments`) && r.method() === 'POST')
  await submitForm(page, '#record-payment', `${detailURL}/payments`)
  const submitted = (await sent).postDataJSON()
  const replay = await page.request.post(`${detailURL}/payments`, { headers, data: submitted })
  expect((await replay.json()).duplicate).toBe(true)
  await expect(page.locator('.pay-txn')).toHaveCount(4)
  await expect(page.locator('#recordPaymentModal')).toHaveCount(0)
  await expect(page.locator('[data-toast-title]')).toHaveText('Payment recorded')
  await expect(page.locator('#payment .order-detail__finance dd').last()).toHaveText(money(0))
  await expect(page.locator('#payment')).toContainText('VerifiedReference123')
  await expect(page.locator('.order-tracker__step[aria-current=step]')).toHaveAttribute('data-workflow-status', 'order_received')
  const reference = await page.locator('.order-detail').getAttribute('data-ref') || ''
  const outstanding = await page.request.get('/payments/outstanding?q=' + encodeURIComponent(reference))
  expect(await outstanding.text()).not.toContain(`href="${detailURL}"`)
  // Clean up only this test's temporary configuration through the original authorized endpoints.
  expect((await page.request.post('/payments/settings/qr/remove', { headers })).status()).toBe(200)
})

test('audit: unpaid later statuses stay outstanding; server-side release guard is a known blocker', async ({ page }) => {
  await login(page, 'admin')
  const { detailURL } = await create(page)
  const csrf = await page.locator('#record-payment input[name=csrf_token]').inputValue()
  await page.request.post(`${detailURL}/confirm-received`, { headers: { 'X-CSRFToken': csrf }, data: {} })
  // Exercise the existing server directly in the isolated test DB to document the missing guard.
  for (const value of values.slice(1)) {
    await page.request.post(`${detailURL}/status`, { form: { csrf_token: csrf, status: value } })
  }
  await page.goto(detailURL)
  await expect(page.locator('.order-tracker__step[aria-current=step]')).toHaveAttribute('data-workflow-status', 'completed')
  await expect(page.locator('#payment .status')).toHaveText('Partially Paid')
  const outstanding = await page.request.get('/payments/outstanding')
  expect(await outstanding.text()).toContain(`href="${detailURL}"`)
})


test('disabled payment methods disappear and are rejected by the original endpoint', async ({ page }) => {
  await login(page, 'admin')
  const { detailURL } = await create(page)
  const csrf = await page.locator('#record-payment input[name=csrf_token]').inputValue()
  const headers = { 'X-CSRFToken': csrf }
  await page.goto('/payments/settings')
  const gcashRow = page.locator('tr').filter({ has: page.locator('.mono', { hasText: /^gcash$/ }) })
  const action = await gcashRow.locator('form').getAttribute('action') || ''
  expect((await page.request.post(action, { headers })).status()).toBe(200)
  try {
    await page.goto(detailURL)
    await page.locator('[data-bs-target="#recordPaymentModal"]').click()
    await expect(page.locator('[data-method=gcash]')).toHaveCount(0)
    await expect(page.locator('#pm-2 option[value=gcash]')).toHaveCount(0)
    const rejected = await page.request.post(`${detailURL}/payments`, { headers, data: { entries: [{ method: 'gcash', amount: '10' }] } })
    expect(rejected.status()).toBe(422)
    await expect(page.locator('.pay-txn')).toHaveCount(2)
  } finally { expect((await page.request.post(action, { headers })).status()).toBe(200) }
})
