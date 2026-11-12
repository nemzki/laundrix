import { expect, test, type Page } from '@playwright/test'

const columns = ['Order Reference', 'Customer', 'Contact Number', 'Date Created', 'Laundry Status', 'Payment Status', 'Action']
async function signIn(page: Page) {
  await page.goto('/auth/login')
  await page.locator('#admin-identifier').fill('browseradmin')
  await page.locator('#admin-password').fill('Browser-Test-Password!42')
  await page.locator('[data-auth-form=admin] button[type=submit]').click()
  await expect(page).toHaveURL(/dashboard/)
}
async function mounted(page: Page) {
  await expect(page.locator('#laundrix-react-orders')).toHaveAttribute('data-ready', 'true')
}
async function geometry(page: Page) {
  return page.locator('#laundrix-react-orders').evaluate(root => {
    const box = (selector: string) => {
      const r = root.querySelector(selector)?.getBoundingClientRect()
      return r ? [r.x, r.y, r.width, r.height] : []
    }
    return { tabs: box('.mo-status-tabs'), search: box('.mo-filters'), heading: box('.mo-table-heading'), table: box('.mo-data-table'), rows: [...root.querySelectorAll('.mo-data-table tbody tr')].map(row => row.getBoundingClientRect().height) }
  })
}

test('first server paint already has the final layout while the JavaScript bundle is held', async ({ page }) => {
  test.setTimeout(60000)
  await signIn(page)
  let release = () => {}
  let gate = Promise.resolve()
  await page.route('**/react/orders.js', async route => { await gate; await route.continue() })
  for (const width of [320, 1024, 1280, 1920]) {
    await page.setViewportSize({ width, height: 900 })
    for (const [name, query] of [['all', ''], ['single', '?status=pending_processing&q=Customer+25'], ['empty', '?status=order_received&q=no-match']] as const) {
      gate = new Promise<void>(resolve => { release = resolve })
      await page.goto('/orders/' + query, { waitUntil: 'commit' })
      const root = page.locator('#laundrix-react-orders')
      await expect(root).toHaveAttribute('data-renderer', 'server')
      // CSS is render-blocking. Inspect its first paint, not the unpainted DOM
      // that the parser exposes before all external stylesheets have arrived.
      await page.waitForFunction(() => [...document.querySelectorAll<HTMLLinkElement>('link[rel=stylesheet]')].every(link => link.sheet))
      await page.evaluate(() => document.fonts.load('400 16px "Geist Sans"'))
      await expect(root).toBeVisible()
      await expect(page.locator('[data-orders-jinja]')).toBeHidden()
      if (name !== 'empty') await expect(root.locator('th')).toHaveText(columns)
      else await expect(root.getByText('No matching orders')).toBeVisible()
      await page.evaluate(() => document.fonts.ready)
      const before = await geometry(page)
      await page.screenshot({ path: `test-results/first-server-${name}-${width}.png` })
      release()
      await mounted(page)
      const after = await geometry(page)
      await page.screenshot({ path: `test-results/first-react-${name}-${width}.png` })
      for (const key of ['tabs', 'search', 'heading', 'table'] as const) {
        after[key].forEach((value, i) => expect(Math.abs(value - before[key][i]), `${name}/${width}/${key}/${i}: ${JSON.stringify({ before, after })}`).toBeLessThanOrEqual(1))
      }
    }
  }
})

test('every status updates once without document navigation or replacing the surrounding UI', async ({ page }) => {
  await signIn(page)
  await page.goto('/orders/')
  await mounted(page)
  await page.evaluate(() => {
    Object.assign(window, {
      stableSidebar: document.querySelector('.lx-sidebar'),
      stableHeader: document.querySelector('.page-header'),
      stableSearch: document.querySelector('#laundrix-react-orders input[type=search]'),
      stableTable: document.querySelector('.mo-data-table'),
      badFrames: [] as string[],
      watchOrders: true,
    })
    const state = window as unknown as { watchOrders: boolean; badFrames: string[] }
    const inspect = () => {
      if (!state.watchOrders) return
      const legacy = document.querySelector<HTMLElement>('[data-orders-jinja]')
      if (legacy && !legacy.hidden) state.badFrames.push('Legacy layout painted')
      const table = document.querySelector('.mo-table-overflow')
      if (table && table.scrollHeight > table.clientHeight + 1) state.badFrames.push('Nested vertical scrolling')
      const headings = document.querySelectorAll('.mo-data-table th')
      if (headings.length !== 7) state.badFrames.push('Wrong columns')
      requestAnimationFrame(inspect)
    }
    requestAnimationFrame(inspect)
  })
  const root = page.locator('#laundrix-react-orders')
  const before = await geometry(page)
  const requests: string[] = []
  page.on('request', request => { if (new URL(request.url()).pathname === '/orders/') requests.push(request.resourceType()) })
  const values = ['', 'order_received', 'pending_processing', 'processing', 'ready_for_pickup', 'picked_up', 'completed']
  for (let round = 0; round < 2; round++) {
    for (const [index, value] of values.entries()) {
      const count = requests.length
      const wasSelected = await root.getByRole('tab').nth(index).getAttribute('aria-selected') === 'true'
      await root.getByRole('tab').nth(index).click()
      await expect(root.locator('input[name=status]')).toHaveValue(value)
      await expect(root.getByRole('tab').nth(index)).toHaveAttribute('aria-selected', 'true')
      await expect(root.locator('th')).toHaveText(columns)
      expect(requests.length - count).toBe(wasSelected ? 0 : 1)
      const after = await geometry(page)
      for (const key of ['tabs', 'search', 'heading'] as const) expect(after[key]).toEqual(before[key])
      expect(await page.evaluate(() => {
        const state = window as unknown as Record<string, Element>
        return state.stableSidebar === document.querySelector('.lx-sidebar') && state.stableHeader === document.querySelector('.page-header') &&
          state.stableSearch === document.querySelector('#laundrix-react-orders input[type=search]') && state.stableTable === document.querySelector('.mo-data-table')
      })).toBe(true)
    }
  }
  expect(requests.every(type => type === 'fetch')).toBe(true)
  expect(await page.evaluate(() => {
    const state = window as unknown as { watchOrders: boolean; badFrames: string[] }
    state.watchOrders = false
    return state.badFrames
  })).toEqual([])
  await page.goBack()
  await expect(root.locator('input[name=status]')).toHaveValue('picked_up')
  await page.goForward()
  await expect(root.locator('input[name=status]')).toHaveValue('completed')
})

test('failed filtering preserves rows and URL; retry works; expired sessions follow Flask redirects', async ({ page }) => {
  await signIn(page)
  await page.goto('/orders/')
  await mounted(page)
  const root = page.locator('#laundrix-react-orders')
  const rows = await root.locator('tbody tr').count()
  await page.route('**/orders/?status=processing', route => route.fulfill({ status: 503, body: 'Unavailable' }))
  await root.getByRole('tab').nth(3).click()
  await expect(root.getByRole('alert')).toContainText('Your current results are still shown')
  await expect(root.locator('tbody tr')).toHaveCount(rows)
  await expect(page).toHaveURL(/\/orders\/$/)
  await page.unroute('**/orders/?status=processing')
  await root.getByRole('button', { name: 'Try again' }).click()
  await expect(root.locator('input[name=status]')).toHaveValue('processing')
  await expect(root.getByRole('alert')).toHaveCount(0)
  await page.context().clearCookies()
  await root.getByRole('tab').nth(6).click()
  await expect(page).toHaveURL(/\/auth\/login/)
})

test('Manage Orders uses the available desktop width with aligned proportional columns', async ({ page }) => {
  await signIn(page)
  await page.goto('/orders/')
  await mounted(page)
  for (const width of [1024, 1280, 1440, 1920, 2560]) {
    await page.setViewportSize({ width, height: 1000 })
    const layout = await page.evaluate(() => {
      const content = document.querySelector<HTMLElement>('.content')!
      const style = getComputedStyle(content)
      const innerWidth = content.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
      const rects = ['.page-header', '.mo-status-tabs', '.mo-filters', '.mo-table-panel'].map(selector => document.querySelector(selector)!.getBoundingClientRect())
      const fitText = (selector: string) => [...document.querySelectorAll(selector)].every(element => {
        const range = document.createRange()
        range.selectNodeContents(element)
        return range.getClientRects().length === 1
      })
      return {
        ratio: innerWidth / document.querySelector('.main')!.getBoundingClientRect().width,
        sidebar: document.querySelector('.lx-sidebar')!.getBoundingClientRect().width,
        aligned: rects.every(r => Math.abs(r.x - rects[0].x) < 1 && Math.abs(r.width - innerWidth) < 1),
        noPageOverflow: document.documentElement.scrollWidth <= window.innerWidth + 1,
        noTableOverflow: (() => { const e = document.querySelector('.mo-table-overflow')!; return e.scrollWidth <= e.clientWidth + 1 && e.scrollHeight <= e.clientHeight + 1 })(),
        badgesFit: [...document.querySelectorAll('.mo-data-table td:nth-child(5) .lx-status')].every(e => e.scrollWidth <= e.clientWidth + 1 && getComputedStyle(e).whiteSpace === 'nowrap'),
        badgeMeasurements: [...document.querySelectorAll('.mo-data-table td:nth-child(5) .lx-status')].map(e => [e.textContent, e.scrollWidth, e.clientWidth, getComputedStyle(e).whiteSpace]),
        phoneSingleLine: fitText('.mo-data-table .mo-contact'),
        referenceSingleLine: fitText('.mo-data-table .mo-reference'),
      }
    })
    expect(layout.ratio).toBeGreaterThanOrEqual(.95)
    expect(layout.sidebar).toBe(256)
    expect(layout.aligned).toBe(true)
    expect(layout.noPageOverflow).toBe(true)
    expect(layout.noTableOverflow).toBe(true)
    expect(layout.badgesFit, `Laundry badge overflow at ${width}px: ${JSON.stringify(layout.badgeMeasurements)}`).toBe(true)
    expect(layout.phoneSingleLine).toBe(true)
    expect(layout.referenceSingleLine).toBe(true)
    await page.screenshot({ path: `test-results/orders-width-${width}.png` })
  }
})

test('rapid duplicate tabs use one request and a superseded response cannot replace the newest filter', async ({ page }) => {
  await signIn(page)
  await page.goto('/orders/')
  await mounted(page)
  let release = () => {}
  const gate = new Promise<void>(resolve => { release = resolve })
  let finished = () => {}
  const settled = new Promise<void>(resolve => { finished = resolve })
  let requests = 0
  await page.route('**/orders/?status=processing', async route => {
    requests++
    await gate
    try { await route.continue() } catch { /* The superseded fetch was intentionally aborted. */ }
    finally { finished() }
  })
  const root = page.locator('#laundrix-react-orders')
  const first = page.waitForRequest('**/orders/?status=processing')
  await root.getByRole('tab').nth(3).click()
  await first
  await root.getByRole('tab').nth(3).click()
  expect(requests).toBe(1)
  await root.getByRole('tab').nth(6).click()
  await expect(root.locator('input[name=status]')).toHaveValue('completed')
  release()
  await settled
  await expect(root.locator('input[name=status]')).toHaveValue('completed')
  await expect(root.getByRole('alert')).toHaveCount(0)
})
