import { expect, test, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'

async function login(page: Page, role: 'admin' | 'staff' = 'admin') {
  await page.goto('/auth/login')
  if (role === 'staff') await page.getByRole('tab', { name: 'Staff', exact: true }).click()
  await page.locator(`#${role}-identifier`).fill(role === 'admin' ? 'browseradmin' : 'staff@example.test')
  await page.locator(`#${role}-password`).fill('Browser-Test-Password!42')
  await page.locator(`form[data-auth-form=${role}] button[type=submit]`).click()
  await expect(page).toHaveURL(/dashboard/)
}
async function ready(page: Page) { await expect(page.locator('[data-outstanding]')).toHaveAttribute('data-state','ready') }
async function open(page: Page) {
  const row = page.locator('.ob-rows [data-order-ref]').first()
  const ref = await row.getAttribute('data-order-ref') || ''
  await row.locator('[data-ob-payment]').click()
  await expect(page.locator('#record-payment')).toBeVisible()
  await expect(page.locator('#recordPaymentModal')).toBeFocused()
  await expect(page.locator('#recordPaymentModal .modal-header')).toContainText(ref)
  return ref
}
for (const role of ['admin','staff'] as const) for (const width of [320,768,1440]) test(`${role} outstanding real data, summaries and shared modal ${width}px`, async ({page}) => {
  const errors: string[]=[]; page.on('pageerror',e => errors.push(e.message))
  await page.setViewportSize({width,height:900}); await login(page,role)
  await page.goto('/payments/outstanding'); await ready(page)
  await expect(page.locator('.ob-table th')).toHaveText(['Order Reference','Customer','Date Created','Laundry Status','Total','Balance','Payment','Action'])
  const countDoc = await (await page.request.get('/orders/?payment=unpaid')).text()
  const total = await page.evaluate(html => new DOMParser().parseFromString(html,'text/html').querySelector('[data-orders-results]')!.getAttribute('data-total'),countDoc)
  await expect(page.locator('[data-unpaid-count]')).toHaveText(total!)
  await expect(page.locator('[data-partial-count]')).not.toHaveText('—')
  await expect(page.getByRole('link',{name:'View fully paid orders',exact:true})).toHaveCount(0)
  await expect(page.locator('.page-actions')).toBeHidden()
  const geometry=await page.locator('.ob-stat').evaluateAll(cards=>cards.map(card=>{
    const box=card.getBoundingClientRect()
    return {top:box.top,width:box.width,height:box.height,offsets:['h2',':scope > strong','p','.ob-stat-icon'].map(selector=>card.querySelector(selector)!.getBoundingClientRect().top-box.top)}
  }))
  for(const card of geometry) {
    expect(Math.abs(card.width-geometry[0].width)).toBeLessThan(1)
    expect(Math.abs(card.height-geometry[0].height)).toBeLessThan(1)
    if(width>=1024) expect(Math.abs(card.top-geometry[0].top)).toBeLessThan(1)
    card.offsets.forEach((offset,index)=>expect(Math.abs(offset-geometry[0].offsets[index])).toBeLessThan(1))
  }
  for (const id of ['ob-payment-filter','ob-sort']) {
    const wrapper=page.locator(`#${id}`).locator('..')
    await wrapper.locator('.ob-select-trigger').click()
    const menu=(await wrapper.locator('.ob-select-menu').boundingBox())!
    expect(menu.x).toBeGreaterThanOrEqual(0); expect(menu.x+menu.width).toBeLessThanOrEqual(width)
    expect(menu.y).toBeGreaterThanOrEqual(0); expect(menu.y+menu.height).toBeLessThanOrEqual(900)
    await page.keyboard.press('Escape'); await expect(wrapper.locator('.ob-select-menu')).toBeHidden()
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  const tableScroll = await page.locator('.ob-table-wrap').evaluate(el => ({ height: el.clientHeight, content: el.scrollHeight, overflow: getComputedStyle(el).overflowY }))
  expect(tableScroll.content).toBeLessThanOrEqual(tableScroll.height)
  expect(tableScroll.overflow).toBe('hidden')
  const ref = await open(page)
  const original = await page.request.get(`/orders/${ref}`)
  expect(await original.text()).toContain('payment_modal.js')
  await expect(page.locator('#pa-1')).toHaveAttribute('value', await page.locator('#pa-1').getAttribute('max') || '')
  const modalFooter = (await page.locator('#recordPaymentModal .modal-footer').boundingBox())!
  expect(modalFooter.y + modalFooter.height).toBeLessThanOrEqual(900)
  await expect(page.locator('[data-method=cash]')).toHaveAttribute('aria-pressed','true')
  await expect(page.locator('[data-method=gcash]')).toBeVisible()
  await page.screenshot({path:`test-results/dashboard/outstanding-${role}-${width}-modal.png`,fullPage:true})
  await page.keyboard.press('Escape'); await expect(page.locator('#recordPaymentModal')).toBeHidden()
  await expect(page.locator(`tr[data-order-ref="${ref}"] [data-ob-payment]`)).toBeFocused()
  // Reopen mounts exactly one shared form/controller, then cancel.
  await open(page); await expect(page.locator('[data-method=cash]')).toHaveCount(1)
  await page.locator('#recordPaymentModal .modal-footer [data-bs-dismiss]').click()
  await expect(page.locator('#recordPaymentModal')).toBeHidden()
  await page.locator('#ob-payment-filter').selectOption('unpaid'); await ready(page)
  expect(await page.locator('.ob-rows [data-payment-status]').evaluateAll(nodes => nodes.every(n => n.getAttribute('data-payment-status')==='unpaid'))).toBe(true)
  await page.locator('#ob-payment-filter').selectOption('partial'); await ready(page)
  expect(await page.locator('.ob-rows [data-payment-status]').evaluateAll(nodes => nodes.every(n => n.getAttribute('data-payment-status')==='partial'))).toBe(true)
  await page.locator('[data-ob-link]').click(); await ready(page)
  await expect(page.locator('#ob-payment-filter')).toHaveValue('outstanding')
  expect(errors).toEqual([])
})

test('shared modal cash, real GCash configuration, validation, split transaction and settlement refresh', async ({page}) => {
  test.setTimeout(90000)
  await login(page); await page.goto('/payments/outstanding?status=unpaid'); await ready(page)
  const originalCount=Number(await page.locator('[data-owing-count]').innerText())
  const ref=await open(page)
  const initialHTML=await (await page.request.get(`/orders/${ref}`)).text()
  const initialPayments=await page.evaluate(html=>new DOMParser().parseFromString(html,'text/html').querySelectorAll('.pay-txn').length,initialHTML)
  const csrf=await page.locator('#record-payment [name=csrf_token]').inputValue()
  const headers={'X-CSRFToken':csrf}
  // Reset only the isolated fixture QR so missing configuration is deterministic.
  expect((await page.request.post('/payments/settings/qr/remove',{headers})).ok()).toBe(true)
  await page.locator('[data-method=gcash]').click()
  await expect(page.locator('[data-payment-config-status]')).toContainText('GCash QR code is not configured.')
  await expect(page.locator('#pr-1')).toHaveAttribute('required','')
  await page.locator('#record-payment button[type=submit]').click()
  expect(await page.locator('#pr-1').evaluate((e:HTMLInputElement)=>e.validity.valueMissing)).toBe(true)
  await page.locator('#recordPaymentModal .modal-footer [data-bs-dismiss]').click(); await expect(page.locator('#recordPaymentModal')).toBeHidden()
  expect((await page.request.post('/payments/settings',{headers,data:{partial_enabled:true,pay_later_enabled:true,gcash_account_name:'Isolated Outstanding QA',gcash_account_number:'09170000000',payment_instructions:'Verify test recipient.'}})).ok()).toBe(true)
  const png=execFileSync('../.venv/Scripts/python.exe',['-c','import io,sys; from PIL import Image; b=io.BytesIO(); Image.new("RGB",(160,160),"blue").save(b,"PNG"); sys.stdout.buffer.write(b.getvalue())'])
  expect((await page.request.post('/payments/settings/qr',{headers,multipart:{image:{name:'isolated-test.png',mimeType:'image/png',buffer:png}}})).ok()).toBe(true)
  await open(page); await page.locator('[data-method=gcash]').click()
  await expect(page.locator('[data-payment-qr]')).toBeVisible()
  await expect(page.locator('[data-payment-qr]')).toHaveAttribute('src',/\/payments\/qr$/)
  await expect(page.locator('[data-payment-account]')).toContainText('Isolated Outstanding QA')
  await page.locator('#pr-1').fill('invalid@reference')
  const rejected=page.waitForResponse(r=>r.url().endsWith(`/orders/${ref}/payments`) && r.request().method()==='POST')
  await page.locator('#record-payment button[type=submit]').click(); expect((await rejected).status()).toBe(422)
  await expect(page.locator('[data-payment-errors]')).toContainText('reference may only contain')
  await expect(page.locator('#pr-1')).toHaveValue('invalid@reference')
  await page.locator('[data-method=cash]').click(); await page.locator('#pr-1').fill('')
  await page.locator('#pa-1').fill('20')
  const partial=page.waitForResponse(r=>r.url().endsWith(`/orders/${ref}/payments`) && r.request().method()==='POST')
  await page.locator('#record-payment button[type=submit]').click(); expect((await partial).status()).toBe(200)
  await expect(page.locator('#recordPaymentModal')).toBeHidden(); await ready(page)
  await page.goto('/payments/outstanding?status=partial'); await ready(page)
  const updated=page.locator(`.ob-rows tr[data-order-ref="${ref}"]`)
  await expect(updated.locator('[data-payment-status]')).toHaveAttribute('data-payment-status','partial')
  await updated.locator('[data-ob-payment]').click(); await expect(page.locator('#record-payment')).toBeVisible()
  await page.locator('#record-payment details > summary').click(); await page.locator('#pm-2').selectOption('cash')
  expect(await page.locator('#pm-2').evaluate((e:HTMLSelectElement)=>e.validity.customError)).toBe(true)
  await page.locator('#pm-2').selectOption('gcash')
  const remaining=Number(await page.locator('#pa-1').inputValue())
  await page.locator('#pa-1').fill(String(remaining/2)); await page.locator('#pa-2').fill(String(remaining/2)); await page.locator('#pr-2').fill('VerifiedOutstanding123')
  const sent=page.waitForRequest(r=>r.url().endsWith(`/orders/${ref}/payments`) && r.method()==='POST')
  await page.locator('#record-payment button[type=submit]').click(); const payload=(await sent).postDataJSON()
  await expect(page.locator('#recordPaymentModal')).toBeHidden(); await ready(page)
  await expect(page.locator(`.ob-rows tr[data-order-ref="${ref}"]`)).toHaveCount(0)
  await expect(page.locator('[data-owing-count]')).toHaveText(String(originalCount-1))
  await expect(page.locator('[data-ob-toast]')).toContainText('Payment recorded')
  const replay=await page.request.post(`/orders/${ref}/payments`,{headers,data:payload}); expect((await replay.json()).duplicate).toBe(true)
  await page.goto(`/orders/${ref}`)
  await expect(page.locator('#payment [data-payment-status]')).toHaveAttribute('data-payment-status','paid')
  await expect(page.locator('.pay-txn')).toHaveCount(initialPayments+3)
  await page.goto('/payments/'); await expect(page.locator('body')).toContainText(ref)
})

test('outstanding load failure, retry, skeleton and modal fetch retry', async ({page}) => {
  await login(page)
  let fail=true
  let release!:()=>void
  const gate=new Promise<void>(resolve=>{release=resolve})
  await page.route('**/payments/outstanding*',async route => {
    if (route.request().resourceType()==='fetch' && fail) { await gate; fail=false; return route.abort('failed') }
    return route.continue()
  })
  await page.goto('/payments/outstanding')
  await expect(page.locator('.ob-skeleton')).toBeVisible(); await expect(page.locator('.ob-skeleton tr')).toHaveCount(10)
  release()
  await expect(page.locator('[data-outstanding]')).toHaveAttribute('data-state','error')
  await expect(page.locator('[data-ob-retry]')).toBeVisible(); await page.locator('[data-ob-retry]').click(); await ready(page)
  let modalFail=true
  await page.route('**/orders/*',route => route.request().resourceType()==='fetch' && modalFail && !route.request().url().includes('?') ? (modalFail=false,route.abort('failed')) : route.continue())
  await page.locator('.ob-rows [data-ob-payment]').first().click()
  await expect(page.locator('[data-ob-modal-status] .btn')).toHaveText('Retry')
  await page.locator('[data-ob-modal-status] .btn').click(); await expect(page.locator('#record-payment')).toBeVisible()
})

test('complete-set search, real sort menus, combined filters, pagination and partial count', async ({page}) => {
  test.setTimeout(90000)
  await login(page)
  await page.goto('/orders/new')
  const csrf=await page.locator('#wizard').getAttribute('data-csrf') || ''
  const wash=await page.locator('input[data-code=wash]').getAttribute('data-id')
  for (const [index, quantity] of [4,1,2].entries()) {
    const response=await page.request.post('/orders/new/confirm',{headers:{'X-CSRFToken':csrf},data:{
      customer:{new:{full_name:`Outstanding Filter QA ${index}`,contact_number:`0918000000${index}`}},
      items:[{kind:'service',id:wash,quantity:String(quantity)}],extras:[],
      payment:index===0 ? {arrangement:'partial',entries:[{method:'cash',amount:'10'}]} : {arrangement:'pay_later',entries:[]},
    }})
    expect(response.ok()).toBe(true)
  }
  await page.goto('/payments/outstanding'); await ready(page)
  const countHTML=await (await page.request.get('/orders/?payment=partial')).text()
  const partialTotal=await page.evaluate(html=>new DOMParser().parseFromString(html,'text/html').querySelector('[data-orders-results]')!.getAttribute('data-total'),countHTML)
  await expect(page.locator('[data-partial-count]')).toHaveText(partialTotal!)
  await expect(page.getByRole('heading',{name:'Partially Paid',exact:true})).toBeVisible()
  await expect(page.locator('.ob-stats')).toContainText('Orders with remaining balances')
  const filter=page.locator('#ob-payment-filter').locator('..')
  const sort=page.locator('#ob-sort').locator('..')
  await filter.locator('.ob-select-trigger').click()
  await expect(filter.locator('[role=option]')).toHaveText(['Unpaid & Partial✓','Unpaid Only✓','Partially Paid Only✓'])
  await expect(filter.locator('[aria-selected=true] .ob-option-check')).toBeVisible()
  const menuBox=(await filter.locator('.ob-select-menu').boundingBox())!
  const controlBox=(await filter.locator('.ob-select-trigger').boundingBox())!
  expect(menuBox.y).toBeGreaterThanOrEqual(controlBox.y+controlBox.height)
  expect(menuBox.width).toBeLessThanOrEqual(195)
  await page.keyboard.press('Escape'); await expect(filter.locator('.ob-select-menu')).toBeHidden()
  await sort.locator('.ob-select-trigger').click()
  await expect(sort.locator('[role=option]')).toHaveText(['Highest Balance✓','Lowest Balance✓','Oldest First✓','Newest First✓'])
  await sort.getByRole('option',{name:'Lowest Balance'}).click(); await ready(page)
  let amounts=await page.locator('.ob-rows [data-balance]').evaluateAll(rows=>rows.map(r=>Number((r as HTMLElement).dataset.balance)))
  expect(amounts).toEqual([...amounts].sort((a,b)=>a-b))
  // Search an actual record from beyond server page one, rather than visible rows.
  const second=await (await page.request.get('/payments/outstanding?status=outstanding&page=2')).text()
  const target=await page.evaluate(html=>{
    const row=new DOMParser().parseFromString(html,'text/html').querySelector('.ob-rows [data-order-ref]')!
    return {ref:row.getAttribute('data-order-ref')!,phone:row.querySelector('.ob-contact')!.textContent!.trim()}
  },second)
  const search=page.locator('#ob-search')
  await search.fill(target.ref.toLowerCase()); await expect(page.locator('.ob-rows [data-order-ref]')).toHaveCount(1)
  await expect(page.locator('.ob-rows [data-order-ref]')).toHaveAttribute('data-order-ref',target.ref)
  await search.fill(target.phone); await expect(page.locator('.ob-rows [data-order-ref]')).toHaveCount(1)
  await search.fill('Outstanding Filter QA'); await expect(page.locator('.ob-rows [data-order-ref]')).toHaveCount(3)
  await filter.locator('.ob-select-trigger').click(); await filter.getByRole('option',{name:'Partially Paid Only'}).click()
  await expect(page.locator('.ob-rows [data-order-ref]')).toHaveCount(1)
  await expect(search).toHaveValue('Outstanding Filter QA')
  await expect(page.locator('#ob-sort')).toHaveValue('lowest')
  await expect(filter.locator('.ob-select-menu')).toBeHidden()
  await expect(filter.locator('.ob-select-trigger')).toContainText('Partially Paid Only')
  await page.reload(); await ready(page); await expect(search).toHaveValue('Outstanding Filter QA')
  await expect(page.locator('#ob-payment-filter')).toHaveValue('partial')
  await expect(page.locator('.ob-rows [data-order-ref]')).toHaveCount(1)
  await page.locator('[data-ob-link]').click(); await ready(page)
  await expect(search).toHaveValue(''); await expect(page.locator('#ob-sort')).toHaveValue('highest')
  amounts=await page.locator('.ob-rows [data-balance]').evaluateAll(rows=>rows.map(r=>Number((r as HTMLElement).dataset.balance)))
  expect(amounts).toEqual([...amounts].sort((a,b)=>b-a))
  const first=await page.locator('.ob-rows [data-order-ref]').evaluateAll(rows=>rows.map(r=>r.getAttribute('data-order-ref')))
  await page.locator('.ob-footer a',{hasText:/^Next$/}).click(); await ready(page)
  const next=await page.locator('.ob-rows [data-order-ref]').evaluateAll(rows=>rows.map(r=>r.getAttribute('data-order-ref')))
  expect(new Set([...first,...next]).size).toBe(first.length+next.length)
  await sort.locator('.ob-select-trigger').click(); await sort.getByRole('option',{name:'Oldest First'}).click()
  await expect(page).toHaveURL(url=>!url.searchParams.has('page') && url.searchParams.get('sort')==='oldest')
  let created=await page.locator('.ob-rows [data-created]').evaluateAll(rows=>rows.map(r=>r.getAttribute('data-created')!))
  expect(created).toEqual([...created].sort())
  await sort.locator('.ob-select-trigger').focus(); await page.keyboard.press('ArrowDown'); await expect(sort.locator('.ob-select-menu')).toBeVisible()
  await page.keyboard.press('Escape'); await expect(sort.locator('.ob-select-menu')).toBeHidden()
  await sort.locator('.ob-select-trigger').click(); await sort.getByRole('option',{name:'Newest First'}).click()
  created=await page.locator('.ob-rows [data-created]').evaluateAll(rows=>rows.map(r=>r.getAttribute('data-created')!))
  expect(created).toEqual([...created].sort().reverse())
  const before=await search.boundingBox(); await search.focus()
  await expect(search).toHaveCSS('box-shadow','none'); await expect(search).toHaveCSS('outline-style','none')
  await expect(page.locator('.ob-search')).toHaveCSS('outline-width','2px'); expect(await search.boundingBox()).toEqual(before)
  await search.fill('No matching order anywhere'); await expect(page.locator('.ob-empty')).toContainText('No orders match your filters.')
  await page.goBack(); await expect(search).toHaveValue('')
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
})

test('incomplete second server page cannot enable misleading local filters', async ({page})=>{
  await login(page)
  let fail=true
  await page.route('**/payments/outstanding?status=outstanding&page=2',route=>fail ? (fail=false,route.abort('failed')) : route.continue())
  await page.goto('/payments/outstanding')
  await expect(page.locator('[data-outstanding]')).toHaveAttribute('data-state','error')
  await expect(page.locator('#ob-search')).toBeDisabled()
  await expect(page.locator('.ob-rows')).toBeHidden()
  await page.locator('[data-ob-retry]').click(); await ready(page)
  await expect(page.locator('#ob-search')).toBeEnabled()
})
