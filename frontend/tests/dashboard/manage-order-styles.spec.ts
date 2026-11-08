import { expect, test } from '@playwright/test'

test('central laundry colors, customer icons and one stable search focus indicator', async ({ page }) => {
  await page.goto('/auth/login')
  await page.locator('#admin-identifier').fill('browseradmin')
  await page.locator('#admin-password').fill('Browser-Test-Password!42')
  await page.locator('form[data-auth-form=admin] button[type=submit]').click()
  await expect(page).toHaveURL(/dashboard/)
  const palette = {
    order_received: ['rgb(224, 242, 254)', 'rgb(7, 89, 133)'],
    pending_processing: ['rgb(254, 243, 199)', 'rgb(146, 64, 14)'],
    processing: ['rgb(219, 234, 254)', 'rgb(30, 64, 175)'],
    ready_for_pickup: ['rgb(204, 251, 241)', 'rgb(17, 94, 89)'],
    picked_up: ['rgb(237, 233, 254)', 'rgb(91, 33, 182)'],
    completed: ['rgb(224, 231, 255)', 'rgb(55, 48, 163)'],
  }
  await expect(page.locator('.dashboard-status').first()).toBeAttached()
  for (const badge of await page.locator('.dashboard-status[data-laundry-status]').all()) {
    const status = await badge.getAttribute('data-laundry-status') as keyof typeof palette
    await expect(badge).toHaveCSS('background-color', palette[status][0])
    await expect(badge).toHaveCSS('color', palette[status][1])
  }
  for (const [status, [background, color]] of Object.entries(palette)) {
    await page.goto(`/orders/?status=${status}`)
    await expect(page.locator('[data-manage-orders]')).toHaveAttribute('data-state', 'ready')
    const badge = page.locator(`.mo-rows [data-laundry-status=${status}]`).first()
    await expect(badge).toHaveCSS('background-color', background)
    await expect(badge).toHaveCSS('color', color)
    await expect(badge).toHaveCSS('font-size', '12px')
    await expect(badge).toHaveCSS('font-weight', '500')
    await expect(badge).toHaveCSS('border-radius', '999px')
    await page.locator('.mo-rows [data-order-summary]').first().click()
    await expect(page.locator('[data-summary-content]')).toBeVisible()
    await expect(page.locator('[data-field=laundry]')).toHaveCSS('background-color', background)
    await expect(page.locator('[data-customer-icon=user-round]')).toBeVisible()
    await expect(page.locator('[data-customer-icon=phone]')).toBeVisible()
    await expect(page.locator('#orderSummaryModal')).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(page.locator('#orderSummaryModal')).toBeHidden()
    await expect(page.locator('.mo-rows [data-order-summary]').first()).toBeFocused()
  }
  for (const width of [320, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    const input = page.locator('#orders-search')
    await input.blur()
    const before = await input.boundingBox()
    await input.focus()
    await expect(input).toHaveCSS('box-shadow', 'none')
    await expect(input).toHaveCSS('outline-style', 'none')
    await expect(input).toBeFocused()
    await expect(page.locator('.mo-search')).toHaveCSS('outline', 'rgb(37, 99, 235) solid 2px')
    expect(await input.boundingBox()).toEqual(before)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  // Payment filter uses the existing server query with the approved integration.
  await expect(page.locator('#orders-payment')).toBeEnabled()
  for (const [status, background, color] of [
    ['unpaid', 'rgb(254, 226, 226)', 'rgb(153, 27, 27)'],
    ['paid', 'rgb(209, 250, 229)', 'rgb(6, 95, 70)'],
  ]) {
    await page.goto(`/payments/outstanding?status=${status}`)
    const badge = page.locator(`[data-payment-status=${status}]`).first()
    await expect(badge).toHaveCSS('background-color', background)
    await expect(badge).toHaveCSS('color', color)
    await expect(badge).toHaveCSS('font-size', '12px')
  }
})
