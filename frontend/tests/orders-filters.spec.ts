import { expect, test, type APIResponse } from '@playwright/test'
import type { OrderSummary, OrdersPageData } from '../src/orders-data'

test('3/1/2/0-result fixtures retain columns and natural height through repeated filters and searches', async ({ page }) => {
  test.setTimeout(90000)
  let source: OrderSummary[] = []
  let document: APIResponse | undefined
  await page.route(/\/orders\/(?:\?.*)?$/, async route => {
    const response = document ??= await route.fetch()
    const current = new URL(route.request().url())
    const html = (await response.text()).replace(
      /(<script type="application\/json" id="laundrix-orders-data">)([\s\S]*?)(<\/script>)/,
      (_match, start, json, end) => {
        const data: OrdersPageData = JSON.parse(json)
        data.term = current.searchParams.get('q') || ''
        data.status = current.searchParams.get('status') || ''
        if (!source.length) {
          const pending = data.filters.find(f => f.value === 'pending_processing')!.label
          const completed = data.filters.find(f => f.value === 'completed')!.label
          source = [data.orders.find(o => o.laundry === pending)!, ...data.orders.filter(o => o.laundry === completed).slice(0, 2)]
          expect(source).toHaveLength(3)
        }
        // Isolated frontend result-count fixtures. Other tests exercise the real Flask query.
        data.filters = data.filters.map(filter => {
          const url = new URL(filter.url, current)
          if (data.term) url.searchParams.set('q', data.term)
          return { ...filter, url: url.pathname + url.search, count: source.filter(o => !filter.value || o.laundry === filter.label).length }
        })
        const label = data.filters.find(f => f.value === data.status)?.label
        data.orders = source.filter(o => (!data.status || o.laundry === label) &&
          `${o.reference} ${o.customer} ${o.contact}`.toLowerCase().includes(data.term.toLowerCase()))
        data.total = data.orders.length
        data.page = 1; data.pages = 1; data.previousUrl = null; data.nextUrl = null
        return start + JSON.stringify(data).replace(/</g, '\\u003c') + end
      },
    )
    await route.fulfill({ response, body: html })
  })
  await page.goto('/auth/login')
  await page.locator('#admin-identifier').fill('browseradmin')
  await page.locator('#admin-password').fill('Browser-Test-Password!42')
  await page.locator('[data-auth-form=admin] button[type=submit]').click()
  await expect(page).toHaveURL(/dashboard/)
  const root = page.locator('#laundrix-react-orders')
  for (const width of [320, 768, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/orders/')
    await expect(root).toHaveAttribute('data-ready', 'true')
    const baseline = await root.locator('.mo-data-table th').evaluateAll(headings => headings.map(h => h.getBoundingClientRect().width))
    for (const [name, count] of [['All orders', 3], ['Pending Processing', 1], ['Completed', 2], ['Order Received', 0], ['Completed', 2], ['Pending Processing', 1], ['All orders', 3]] as const) {
      await root.getByRole('tab', { name: new RegExp(`^${name}`) }).click()
      await expect(root).toHaveAttribute('data-ready', 'true')
      await expect(root.locator('.mo-table-heading')).toContainText(`${count} ${name === 'All orders' ? '' : 'matching '}${count === 1 ? 'order' : 'orders'}`)
      await expect(root.locator('.mo-data-table tbody tr')).toHaveCount(count)
      if (count) {
        const metrics = await root.locator('.mo-table-overflow').evaluate(element => {
          const table = element.querySelector('table')!
          return {
            natural: element.scrollHeight <= element.clientHeight + 1,
            height: element.getBoundingClientRect().height,
            tableHeight: table.getBoundingClientRect().height,
            columns: [...table.querySelectorAll('th')].map(h => h.getBoundingClientRect().width),
            badgesFit: [...table.querySelectorAll('[data-slot=badge]')].every(badge => badge.scrollHeight <= badge.clientHeight + 1),
          }
        })
        expect(metrics.natural).toBe(true)
        expect(metrics.badgesFit).toBe(true)
        if (width >= 768) {
          expect(metrics.height - metrics.tableHeight).toBeLessThanOrEqual(18) // only a horizontal scrollbar on tablet
          metrics.columns.forEach((value, index) => expect(Math.abs(value - baseline[index])).toBeLessThan(1))
        }
        if (width >= 1280) expect(await root.locator('.mo-table-overflow').evaluate(e => e.scrollWidth <= e.clientWidth + 1)).toBe(true)
      } else {
        await expect(root.getByText('No matching orders')).toBeVisible()
        expect((await root.locator('.mo-table-panel').boundingBox())!.height).toBeLessThan(210)
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      if (name === 'Pending Processing') await page.screenshot({ path: `test-results/orders-single-${width}.png` })
    }
    await root.getByRole('tab', { name: /^Pending Processing/ }).click()
    await root.getByLabel('Search orders').fill(source[0].reference)
    await root.getByRole('button', { name: 'Search', exact: true }).click()
    await expect(page).toHaveURL(/status=pending_processing/)
    await expect(root.locator('.mo-data-table tbody tr')).toHaveCount(1)
    await root.getByLabel('Search orders').fill('no-match')
    await root.getByRole('button', { name: 'Search', exact: true }).click()
    await expect(root.getByText('No matching orders')).toBeVisible()
    await root.getByRole('link', { name: 'Clear', exact: true }).click()
    await expect(page).toHaveURL(/\/orders\/$/)
    await expect(root.locator('.mo-data-table tbody tr')).toHaveCount(3)
    await expect(root.getByRole('combobox')).toHaveCount(0)
  }
})
