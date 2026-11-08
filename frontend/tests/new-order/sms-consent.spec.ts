import { expect, test, type Page } from '@playwright/test'

async function next(page: Page, step: number) {
  await page.locator('#btn-next').click()
  await expect(page.locator(`.wstep[data-step="${step}"]`)).toBeVisible()
}

async function start(page: Page) {
  await page.goto('/orders/new')
  await expect(page.locator('#sms-consent')).not.toBeChecked()
  await expect(page.locator('#sms-consent')).not.toHaveAttribute('required', '')
  await page.locator('#cust-search').fill('Customer 00')
  await page.locator('#cust-results').getByRole('button', { name: /Customer 00/ }).click()
  await expect(page.locator('#sms-consent')).not.toBeChecked()
}

async function ready(page: Page, reference: string, csrf: string) {
  // Fixture SMS is disabled. No provider network calls may occur.
  const received = await page.request.post(`/orders/${reference}/confirm-received`, {
    headers: { 'X-CSRFToken': csrf }, data: {},
  })
  expect((await received.json()).ok).toBe(true)
  await page.reload()
  await expect(page.locator('#sms')).toContainText('A text message will be prepared')
  for (const status of ['pending_processing', 'processing', 'ready_for_pickup']) {
    await page.locator(`[data-status-update][data-status="${status}"]`).click()
    const modal = page.locator('#statusUpdateModal')
    await expect(modal).toBeVisible()
    const response = page.waitForResponse(r => r.url().endsWith(`/orders/${reference}/status`) && r.request().method() === 'POST')
    await modal.locator('button[type=submit]').click()
    expect((await response).status()).toBe(302)
    await expect(modal).toBeHidden()
  }
}

async function confirm(page: Page, consent: boolean) {
  const csrf = await page.locator('#wizard').getAttribute('data-csrf') || ''
  page.once('dialog', dialog => dialog.accept())
  const request = page.waitForRequest(r => r.url().endsWith('/orders/new/confirm') && r.method() === 'POST')
  await page.locator('#btn-confirm').click()
  expect((await request).postDataJSON().sms_consent).toBe(consent)
  await expect(page).toHaveURL(/\/confirmation$/)
  const reference = await page.locator('#order-created').getAttribute('data-order-reference') || ''
  await page.getByRole('link', { name: 'Open Full Order', exact: true }).click()
  return { reference, csrf }
}

for (const role of ['admin', 'staff'] as const) for (const width of [320, 1440]) {
  test(`${role} per-order SMS consent persistence, Review and original status flow at ${width}px`, async ({ page }) => {
    test.setTimeout(60000)
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/auth/login')
    if (role === 'staff') await page.getByRole('tab', { name: 'Staff', exact: true }).click()
    await page.locator(`#${role}-identifier`).fill(role === 'admin' ? 'browseradmin' : 'staff@example.test')
    await page.locator(`#${role}-password`).fill('Browser-Test-Password!42')
    await page.locator(`form[data-auth-form=${role}] button[type=submit]`).click()
    await expect(page).toHaveURL(/dashboard/)
    await start(page)
    await page.locator('#sms-consent').check()
    await next(page, 2)
    await page.locator('#btn-back').click()
    await expect(page.locator('#sms-consent')).toBeChecked()
    await next(page, 2)
    await page.locator('input[data-code=wash]').locator('..').click()
    await next(page, 3)
    await page.locator('#order-notes').fill('Order-only handling instructions')
    await next(page, 4)
    await page.locator('input[name=arrangement][value=pay_later]').locator('..').click()
    await next(page, 5)
    await expect(page.locator('#rev-sms')).toHaveText('Enabled')
    await expect(page.locator('.wstep[data-step="5"] input[type=checkbox]')).toHaveCount(0)
    await page.getByRole('button', { name: 'Change customer', exact: true }).click()
    await page.locator('#sms-consent').uncheck()
    await expect(page.locator('#rev-sms')).toHaveText('Not enabled')
    await page.locator('#sms-consent').check()
    for (const step of [2, 3, 4, 5]) await next(page, step)
    await page.getByRole('button', { name: 'Edit Details', exact: true }).click()
    await expect(page.locator('#order-notes')).toHaveValue('Order-only handling instructions')
    await expect(page.locator('#sms-consent')).toBeChecked()
    await next(page, 4); await next(page, 5)
    const first = await confirm(page, true)
    await expect(page.locator('#sms .kv dd').first()).toContainText('Yes')
    await expect(page.locator('#sms .kv dd').first().locator('.inline-note')).toBeVisible()
    await expect(page.locator('#sms .status')).toHaveCount(0) // no notification created at order/payment creation
    await ready(page, first.reference, first.csrf)
    await expect(page.locator('#sms .status')).toHaveText('Pending')
    await expect(page.locator('#sms')).toContainText('SMS is disabled. Nothing has been sent')
    await expect(page.locator('[data-sms-retry]')).toHaveCount(0)
    await expect(page.locator('#payment .status')).toHaveText('Unpaid')
    await page.goto(`/orders/?q=${encodeURIComponent(first.reference)}&status=ready_for_pickup`)
    await expect(page.locator('#orders-search')).toHaveValue(first.reference)
    await expect(page.locator('[data-manage-orders]')).toHaveAttribute('data-state','ready')
    await expect(page.locator('.mo-tab[data-status=ready_for_pickup]')).toHaveAttribute('aria-current','page')
    await page.locator('.mo-rows [data-order-summary]').first().click()
    await expect(page.locator('#orderSummaryModal')).toBeVisible()
    await page.locator('#orderSummaryModal').getByRole('link',{name:'Open Full Order',exact:true}).click()
    await expect(page.locator('#sms .status')).toHaveText('Pending')
    // A new order for the same previously consented customer must default to no consent.
    await start(page)
    await next(page, 2)
    await page.locator('input[data-code=wash]').locator('..').click()
    await next(page, 3); await next(page, 4)
    await page.locator('input[name=arrangement][value=full]').locator('..').click()
    await page.locator('input[data-pay-method][value=cash]').locator('..').click()
    await next(page, 5)
    await expect(page.locator('#rev-sms')).toHaveText('Not enabled')
    const second = await confirm(page, false)
    await expect(page.locator('#sms .kv dd').first()).toHaveText('No')
    const receipt = await page.request.post(`/orders/${second.reference}/confirm-received`, { headers: { 'X-CSRFToken': second.csrf }, data: {} })
    expect((await receipt.json()).ok).toBe(true)
    await page.reload()
    for (const status of ['pending_processing', 'processing', 'ready_for_pickup']) {
      const result = await page.request.post(`/orders/${second.reference}/status`, { form: { csrf_token: second.csrf, status } })
      expect(result.status()).toBe(200)
    }
    await page.reload()
    await expect(page.locator('#sms .status')).toHaveText('Skipped — no consent')
    await expect(page.locator('#payment .status')).toHaveText('Paid')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
}
