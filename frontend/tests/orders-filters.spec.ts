import { expect, test } from '@playwright/test'

test('3/1/2/0-result fixtures retain columns and natural height through repeated filters and searches', async ({ page }, testInfo) => {
  test.setTimeout(90000)
  await page.goto('/auth/login')
  await page.locator('#admin-identifier').fill('browseradmin')
  await page.locator('#admin-password').fill('Browser-Test-Password!42')
  await page.locator('[data-auth-form=admin] button[type=submit]').click()
  await expect(page).toHaveURL(/dashboard/)

  const urls = ['/orders/?q=no-match', '/orders/?status=pending_processing', '/orders/?status=completed']
  const [empty, pending, completed] = await Promise.all(urls.map(async url => {
    const response = await page.request.get(url)
    expect(response.ok()).toBe(true)
    return response.text()
  }))
  const source = await page.evaluate(({ pending, completed }) => {
    const rows = (html: string, count: number) => Array.from(new DOMParser().parseFromString(html, 'text/html')
      .querySelectorAll<HTMLTableRowElement>('.mo-rows tr[data-ref]')).slice(0, count).map(row => ({
      html: row.outerHTML,
      reference: row.dataset.ref!,
      status: row.dataset.laundry!,
      text: row.textContent!.toLowerCase(),
    }))
    return [...rows(pending, 1), ...rows(completed, 2)]
  }, { pending, completed })
  expect(source.map(row => row.status)).toEqual(['pending_processing', 'completed', 'completed'])

  await page.route(/\/orders\/(?:\?.*)?$/, async route => {
    if (route.request().resourceType() !== 'fetch') return route.continue()
    const url = new URL(route.request().url())
    const status = url.searchParams.get('status') || ''
    const query = url.searchParams.get('q') || ''
    const matching = source.filter(row => (!status || row.status === status) && row.text.includes(query.toLowerCase()))
    const body = await page.evaluate(({ empty, source, matching, status, query }) => {
      const doc = new DOMParser().parseFromString(empty, 'text/html')
      const results = doc.querySelector<HTMLElement>('[data-orders-results]')!
      const tabs = doc.querySelector('.mo-tabs')!
      results.dataset.total = String(matching.length)
      if (matching.length) results.querySelector('.mo-rows')!.innerHTML = matching.map(row => row.html).join('')
      const [range, total] = results.querySelectorAll('.mo-footer > span strong')
      range.textContent = matching.length ? `1–${matching.length}` : '0–0'
      total.textContent = String(matching.length)
      for (const tab of tabs.querySelectorAll<HTMLAnchorElement>('.mo-tab')) {
        const value = tab.dataset.status || ''
        const params = new URLSearchParams()
        if (query) params.set('q', query)
        if (value) params.set('status', value)
        tab.setAttribute('href', params.size ? `/orders/?${params}` : '/orders/')
        tab.classList.toggle('is-active', status === value)
        if (status === value) tab.setAttribute('aria-current', 'page')
        else tab.removeAttribute('aria-current')
        tab.querySelector('span')!.textContent = String(source.filter(row => !value || row.status === value).length)
      }
      return results.outerHTML + tabs.outerHTML
    }, { empty, source, matching, status, query })
    await route.fulfill({ contentType: 'text/html', body })
  })

  const root = page.locator('[data-manage-orders]')
  const rows = root.locator('.mo-rows tr[data-ref]')
  const wrapper = root.locator('.mo-table-wrap')
  const headers = root.locator('.mo-table th')
  const ready = () => expect(root).toHaveAttribute('data-state', 'ready')
  const columns = () => headers.evaluateAll(cells => cells.map(cell => cell.getBoundingClientRect().width))
  const selectStatus = async (status: string) => {
    const tab = status ? `.mo-tab[data-status="${status}"]` : '.mo-tab:not([data-status])'
    await root.locator(tab).click({ timeout: 5000 })
    await expect(page).toHaveURL(url => (url.searchParams.get('status') || '') === status)
    await ready()
  }

  for (const width of [320, 768, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/orders/')
    await ready()
    const baseline = await columns()
    for (const [status, count] of [
      ['', 3], ['pending_processing', 1], ['completed', 2], ['order_received', 0],
      ['completed', 2], ['pending_processing', 1], ['', 3],
    ] as const) {
      await selectStatus(status)
      await expect(rows).toHaveCount(count)
      await expect(root.locator('[data-orders-results]')).toHaveAttribute('data-total', String(count))
      const metrics = await wrapper.evaluate(element => ({
        natural: element.scrollHeight <= element.clientHeight + 1,
        heightGap: Math.abs(element.clientHeight - element.querySelector('table')!.getBoundingClientRect().height),
        fitsHorizontally: element.scrollWidth <= element.clientWidth + 1,
        badgesFit: Array.from(element.querySelectorAll('.mo-rows .status')).every(
          badge => badge.scrollHeight <= badge.clientHeight + 1,
        ),
      }))
      expect(metrics.natural).toBe(true)
      expect(metrics.heightGap).toBeLessThanOrEqual(1)
      expect(metrics.badgesFit).toBe(true)
      if (width === 1440) expect(metrics.fitsHorizontally).toBe(true)
      const widths = await columns()
      widths.forEach((value, index) => expect(Math.abs(value - baseline[index])).toBeLessThan(1))
      if (count === 0) {
        await expect(root.getByText('No orders match your filters.')).toBeVisible()
        await expect(root.locator('.mo-rows tr')).toHaveCount(1)
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      if (status === 'pending_processing') await page.screenshot({ path: testInfo.outputPath(`orders-single-${width}.png`) })
    }

    await selectStatus('pending_processing')
    const search = root.locator('#orders-search')
    await search.fill(source[0].reference)
    await expect(page).toHaveURL(url => url.searchParams.get('status') === 'pending_processing'
      && url.searchParams.get('q') === source[0].reference)
    await ready()
    await expect(rows).toHaveCount(1)
    await search.fill('no-match')
    await expect(root.getByText('No orders match your filters.')).toBeVisible()
    await root.locator('.mo-filters [data-clear-filters]').click()
    await expect(page).toHaveURL(/\/orders\/$/)
    await ready()
    await expect(rows).toHaveCount(3)
    await expect(root.locator('#orders-payment')).toBeEnabled()
  }
})
