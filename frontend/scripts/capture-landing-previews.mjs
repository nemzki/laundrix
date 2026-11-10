/* Capture the original app design with synthetic data. Start tests/frontend/serve_react.py first. */
import fs from 'node:fs/promises'
import { chromium } from '@playwright/test'

const base = 'http://127.0.0.1:8771'
const destination = new URL('../../app/landing/static/previews/', import.meta.url)
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' })
try {
  await page.goto(base + '/auth/login')
  await page.locator('#admin-identifier').fill('browseradmin')
  await page.locator('#admin-password').fill('Browser-Test-Password!42')
  await page.locator('form[data-auth-form=admin] button[type=submit]').click()
  await page.waitForURL(/dashboard/)
  const fixture = JSON.parse(await page.locator('#laundrix-dashboard-data').textContent())
  if (fixture.user.name !== 'Browser Admin' || fixture.metrics.find(metric => metric.key === 'total_orders')?.value !== '28') {
    throw new Error('Capture requires the fresh isolated browser fixture; refusing other application data.')
  }
  await fs.mkdir(destination, { recursive: true })
  const manifest = { source: 'Original Laundrix Flask UI', data: 'Synthetic browser fixture records', viewport: { width: 1440, height: 1000 }, screens: [] }
  for (const [name, route] of [['dashboard', '/dashboard/'], ['orders', '/orders/'], ['payments', '/payments/']]) {
    await page.goto(base + route, { waitUntil: 'domcontentloaded' })
    if (await page.locator('#laundrix-dashboard').count()) await page.locator('#laundrix-dashboard[data-ready=true]').waitFor()
    if (await page.locator('[data-manage-orders]').count()) await page.locator('[data-manage-orders][data-state=ready]').waitFor()
    await page.evaluate(() => {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
      while (walker.nextNode()) walker.currentNode.textContent = walker.currentNode.textContent.replaceAll('Browser Admin', 'Sample Admin')
    })
    await page.evaluate(() => document.fonts.ready)
    manifest.screens.push({ name, route, title: await page.locator('h1').innerText(), fields: await page.locator('main th').allTextContents(), sections: await page.locator('main h2').allTextContents(), metrics: await page.locator('.dashboard-metric-label').allTextContents(), filters: await page.locator('select[name=kind] option').allTextContents() })
    await page.screenshot({ path: new URL(name + '.png', destination).pathname.replace(/^\/(\w:)/, '$1') })
    console.log('Captured original ' + name + ' design with fixture records.')
  }
  await fs.writeFile(new URL('manifest.json', destination), JSON.stringify(manifest, null, 2) + '\n')
} finally { await browser.close() }
