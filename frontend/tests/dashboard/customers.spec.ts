import { expect, test, type Page } from '@playwright/test'

async function login(page: Page, role: 'admin'|'staff'='admin') {
  await page.goto('/auth/login')
  if(role==='staff') await page.getByRole('tab',{name:'Staff',exact:true}).click()
  await page.locator(`#${role}-identifier`).fill(role==='admin' ? 'browseradmin' : 'staff@example.test')
  await page.locator(`#${role}-password`).fill('Browser-Test-Password!42')
  await page.locator(`form[data-auth-form=${role}] button[type=submit]`).click()
  await expect(page).toHaveURL(/dashboard/)
}
async function ready(page: Page) {await expect(page.locator('[data-customer-directory]')).toHaveAttribute('data-state','ready')}
const rows=(page: Page)=>page.locator('.cm-table tr[data-customer-id]')

for(const width of [320,768,1440]) test(`customer directory and right-side profile ${width}px`,async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
  await page.setViewportSize({width,height:900});await login(page);await page.goto('/orders/customers');await ready(page)
  await expect(page.locator('.cm-table th')).toHaveText(['Customer','Contact Number','Orders','Last Order','Balance','Action'])
  await expect(rows(page)).toHaveCount(15)
  await expect(page.locator('[data-directory-count]')).toHaveText('28')
  const wrap=page.locator('.cm-table-wrap')
  await expect(wrap).toHaveCSS('overflow-y','hidden');await expect(wrap).toHaveCSS('max-height','none')
  await expect(page.locator('.cm-table th').nth(2)).toHaveCSS('text-align','right');await expect(page.locator('.cm-table th').nth(4)).toHaveCSS('text-align','right')
  await expect(rows(page).first().locator('.num').last()).toHaveCSS('font-variant-numeric','tabular-nums')
  expect((await page.locator('.cm-search').boundingBox())!.height).toBe(36);expect((await page.locator('#customer-filter').boundingBox())!.height).toBe(36)
  const edit=rows(page).first().locator('[data-edit-customer]');expect((await edit.boundingBox())!.width).toBe(36)
  await edit.scrollIntoViewIfNeeded();await edit.focus();await expect(page.getByRole('tooltip')).toHaveText('Edit Customer')
  await expect(edit).toHaveAccessibleDescription('Edit Customer');await page.keyboard.press('Escape');await expect(page.getByRole('tooltip')).toBeHidden()
  const first=rows(page).first(),url=await first.getAttribute('data-customer-url') || ''
  const saved=(await (await page.request.get(url)).json()).customer
  await first.locator('[data-view-customer]').click()
  await expect(page.locator('#customerSheet')).toBeFocused()
  await expect(page.locator('#customerSheetTitle')).toHaveText(saved.full_name)
  await expect(page.locator('.cm-profile-contact')).toContainText(saved.contact_number)
  const server=await page.evaluate(html=>{
    const doc=new DOMParser().parseFromString(html,'text/html')
    return {paid:doc.querySelector('[data-profile-paid]')!.textContent!,balance:doc.querySelector('[data-profile-balance]')!.textContent!,orders:doc.querySelector('[data-profile-orders]')!.textContent!,refs:Array.from(doc.querySelectorAll('[data-history-reference]')).map(el=>el.getAttribute('data-history-reference'))}
  },saved.profile_html)
  await expect(page.locator('[data-profile-paid]')).toHaveText(server.paid)
  await expect(page.locator('[data-profile-balance]')).toHaveText(server.balance)
  await expect(page.locator('[data-profile-orders]')).toHaveText(server.orders)
  expect(await page.locator('[data-history-reference]').evaluateAll(els=>els.map(el=>el.getAttribute('data-history-reference')))).toEqual(server.refs)
  const panel=(await page.locator('#customerSheet').boundingBox())!,footer=(await page.locator('.cm-sheet-footer').boundingBox())!
  expect(panel.x+panel.width).toBeCloseTo(width,0);expect(panel.x).toBeGreaterThanOrEqual(0);expect(footer.y+footer.height).toBeLessThanOrEqual(900)
  await page.screenshot({path:`test-results/dashboard/customers-${width}-sheet.png`,fullPage:true})
  await page.keyboard.press('Escape');await expect(page.locator('#customerSheet')).toBeHidden()
  await expect(first.locator('[data-view-customer]')).toBeFocused()
  await first.locator('[data-edit-customer]').click()
  await expect(page.locator('#customer-name')).toHaveValue(saved.full_name)
  await expect(page.locator('#customer-mobile')).toHaveValue(saved.contact_number)
  await expect(page.locator('#customer-name')).toBeEnabled()
  await expect(page.locator('#customerModalTitle')).toHaveText('Edit Customer')
  await expect(page.locator('#customerForm [name=email],#customerForm [name=address],#customerForm [name=notes]')).toHaveCount(0)
  await page.screenshot({path:`test-results/dashboard/customers-${width}-edit.png`,fullPage:true})
  await page.locator('#customerModal .modal-footer [data-bs-dismiss]').click();await expect(page.locator('#customerModal')).toBeHidden()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:`test-results/dashboard/customers-${width}.png`,fullPage:true})
  expect(errors).toEqual([])
})

test('server-wide search, balance filters, stable pagination and native fallback',async({page,browser})=>{
  await login(page);await page.goto('/orders/customers');await ready(page)
  const first=await rows(page).evaluateAll(els=>els.map(el=>el.getAttribute('data-customer-id')))
  await page.locator('.cm-pagination a',{hasText:'Next'}).click();await expect(page).toHaveURL(/page=2/);await ready(page)
  const second=await rows(page).evaluateAll(els=>els.map(el=>el.getAttribute('data-customer-id')))
  expect(new Set([...first,...second]).size).toBe(28)
  await page.locator('#customer-search').fill('customer 00');await expect(page).toHaveURL(url=>url.searchParams.get('q')==='customer 00' && !url.searchParams.has('page'));await ready(page)
  await expect(rows(page)).toHaveCount(1);await expect(page.locator('[data-directory-count]')).toHaveText('28')
  await page.locator('#customer-filter').selectOption('owing');await ready(page);await expect(rows(page)).toHaveCount(1)
  await page.locator('#customer-filter').selectOption('settled');await ready(page);await expect(page.locator('.cm-empty')).toContainText('No customers match')
  await page.locator('[data-customer-page]').click();await ready(page)
  await page.locator('#customer-filter').selectOption('settled');await ready(page)
  await expect(rows(page)).toHaveCount(9)
  await page.locator('#customer-search').fill('09170000001');await expect(page).toHaveURL(/q=09170000001/);await ready(page);await expect(rows(page)).toHaveCount(1)
  await page.goBack();await ready(page);await expect(page.locator('#customer-search')).toHaveValue('')
  const context=await browser.newContext({storageState:await page.context().storageState(),javaScriptEnabled:false})
  try {const native=await context.newPage();await native.goto('http://127.0.0.1:8771/orders/customers');await native.locator('#customer-search').fill('Customer 00');await native.locator('.cm-native-submit').click();await expect(native.locator('.cm-table tr[data-customer-id]')).toHaveCount(1)} finally {await context.close()}
})

test('real add/edit persistence, duplicate guard, validation and sheet refresh',async({page})=>{
  await login(page);await page.goto('/orders/customers');await ready(page)
  await page.locator('[data-add-customer]').click()
  await expect(page.locator('#customerModalTitle')).toHaveText('Add Customer')
  await page.locator('#customer-name').fill('Browser Customer QA');await page.locator('#customer-mobile').fill('09183334444')
  let release!:()=>void;const gate=new Promise<void>(resolve=>{release=resolve});let posts=0
  await page.route('**/orders/customers',async route=>{if(route.request().method()==='POST'){posts++;await gate}return route.continue()})
  const created=page.waitForResponse(r=>r.url().endsWith('/orders/customers') && r.request().method()==='POST')
  await page.locator('#customerForm [type=submit]').click();await expect(page.locator('#customerForm [type=submit]')).toBeDisabled()
  await page.locator('#customerForm').dispatchEvent('submit');expect(posts).toBe(1);release()
  const response=await created;expect(response.status()).toBe(200);const saved=(await response.json()).customer
  await expect(page.locator('#customerModal')).toBeHidden();await expect(page.locator('#customerSheetTitle')).toHaveText('Browser Customer QA');await ready(page)
  await expect(page.locator('[data-directory-count]')).toHaveText('29')
  await expect(page.locator('.cm-history-empty')).toHaveText('No orders yet for this customer.')
  await page.locator('[data-sheet-edit]').click();await expect(page.locator('#customerSheet')).toBeHidden()
  await expect(page.locator('#customer-name')).toHaveValue('Browser Customer QA')
  await page.locator('#customer-mobile').fill('invalid@number')
  const invalid=page.waitForResponse(r=>r.url().endsWith(saved.url) && r.request().method()==='POST')
  await page.locator('#customerForm [type=submit]').click();expect((await invalid).status()).toBe(422)
  await expect(page.locator('#customerModal')).toBeVisible();await expect(page.locator('#customer-mobile')).toHaveValue('invalid@number')
  await expect(page.locator('#customer-mobile')).toHaveAttribute('aria-invalid','true')
  await page.locator('#customer-name').fill('Updated Customer QA');await page.locator('#customer-mobile').fill('09185556666')
  const edited=page.waitForResponse(r=>r.url().endsWith(saved.url) && r.request().method()==='POST')
  await page.locator('#customerForm [type=submit]').click();expect((await edited).status()).toBe(200)
  await expect(page.locator('#customerModal')).toBeHidden();await expect(page.locator('#customerSheetTitle')).toHaveText('Updated Customer QA')
  await expect(page.locator('.cm-profile-contact')).toContainText('09185556666')
  const actual=(await (await page.request.get(saved.url)).json()).customer
  expect(actual.full_name).toBe('Updated Customer QA');expect(actual.contact_number).toBe('09185556666')
  await expect(page.locator('[data-customer-toast]')).toContainText('Customer updated')
  await page.locator('#customerSheet [data-bs-dismiss]').click();await expect(page.locator('#customerSheet')).toBeHidden()
  await page.locator('[data-add-customer]').click();await page.locator('#customer-name').fill('Explicit Duplicate QA');await page.locator('#customer-mobile').fill('09185556666')
  await page.locator('#customerForm [type=submit]').click();await expect(page.locator('[data-customer-duplicate]')).toBeVisible()
  await expect(page.locator('[name=confirm_duplicate]')).not.toBeChecked()
  await page.locator('[name=confirm_duplicate]').check();await page.locator('#customerForm [type=submit]').click()
  await expect(page.locator('#customerModal')).toBeHidden();await expect(page.locator('#customerSheetTitle')).toHaveText('Explicit Duplicate QA')
  await page.locator('.cm-sheet-footer a').click();await expect(page).toHaveURL(/\/orders\/new$/)
  await expect(page.locator('#wizard')).toBeVisible()
})

test('customer profile fetch retry and Staff permission remain enforced',async({page})=>{
  await login(page);await page.goto('/orders/customers');await ready(page)
  let fail=true
  await page.route('**/orders/customers/*',route=>route.request().method()==='GET' && fail ? (fail=false,route.abort('failed')) : route.continue())
  await rows(page).first().locator('[data-view-customer]').click()
  await expect(page.locator('#customerSheet').getByRole('button',{name:'Retry',exact:true})).toBeVisible()
  await page.locator('#customerSheet').getByRole('button',{name:'Retry',exact:true}).click();await expect(page.locator('[data-customer-profile]')).toBeVisible()
  await page.locator('#customerSheet [data-bs-dismiss]').click();await expect(page.locator('#customerSheet')).toBeHidden()
  expect((await page.request.post('/orders/customers',{data:{full_name:'No CSRF',contact_number:'09170000011'}})).status()).toBe(400)
  const context=await page.context().browser()!.newContext();const staff=await context.newPage()
  try {await login(staff,'staff');expect((await staff.request.get('/orders/customers')).status()).toBe(403);expect((await staff.request.get('/orders/customers/1')).status()).toBe(403)} finally {await context.close()}
})


test('four real customer records expand naturally and preserve layout across viewport sizes',async({page})=>{
  await login(page);await page.goto('/orders/customers');await ready(page)
  const csrf=await page.locator('#customerForm [name=csrf_token]').inputValue()
  for(let i=0;i<4;i++){
    const response=await page.request.post('/orders/customers',{headers:{'X-CSRFToken':csrf},data:{full_name:'Polish Four '+i+' '+('Long Customer Name '.repeat(6)),contact_number:'0918999000'+i}})
    expect(response.status()).toBe(200)
  }
  await page.locator('#customer-search').fill('Polish Four');await expect(page).toHaveURL(/q=Polish/);await ready(page);await expect(rows(page)).toHaveCount(4)
  for(const width of [320,768,1440]){
    await page.setViewportSize({width,height:900});await expect(rows(page)).toHaveCount(4)
    const main=await page.locator('main.content').boundingBox(),wrap=page.locator('.cm-table-wrap')
    await expect(wrap).toHaveCSS('overflow-y','hidden');await expect(wrap).toHaveCSS('max-height','none')
    const bounds=(await wrap.boundingBox())!,table=(await page.locator('.cm-table').boundingBox())!,pager=(await page.locator('.cm-pagination').boundingBox())!
    expect(Math.abs(bounds.height-table.height)).toBeLessThanOrEqual(20);expect(pager.y).toBeCloseTo(bounds.y+bounds.height,0)
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
    expect(await rows(page).evaluateAll(els=>els.every(row=>{const actions=row.querySelector('.cm-actions')!,name=row.querySelector('.cm-customer strong')!;return actions.scrollWidth<=actions.clientWidth && name.scrollWidth<=name.clientWidth}))).toBe(true)
    const edit=rows(page).first().locator('[data-edit-customer]');await edit.focus();await edit.hover();await expect(page.getByRole('tooltip')).toHaveText('Edit Customer');await page.keyboard.press('Escape');await expect(page.getByRole('tooltip')).toBeHidden()
    expect(await page.locator('main.content').boundingBox()).toEqual(main)
    await page.screenshot({path:`test-results/dashboard/customers-polish-${width}-${test.info().project.use.colorScheme||'light'}.png`,fullPage:true})
  }
})


test('Customers styles are present before enhancement and after refresh',async({page})=>{
  await login(page)
  let release!:()=>void
  const gate=new Promise<void>(resolve=>{release=resolve})
  await page.route('**/js/customers.js',async route=>{await gate;await route.continue()})
  await page.goto('/orders/customers',{waitUntil:'commit'})
  try {
    await expect(page.locator('.cm-table')).toBeVisible();await expect(page.locator('.cm-table-wrap')).toHaveCSS('overflow-y','hidden')
    await expect(page.locator('[data-edit-customer]').first()).toBeHidden()
    await expect(page.locator('.cm-native-submit')).toBeVisible()
    await expect(page.locator('.cm-panel')).toHaveCSS('border-radius','12px')
  } finally {release()}
  await ready(page);await expect(page.locator('[data-edit-customer]').first()).toBeVisible()
  await page.reload();await ready(page);await expect(page.locator('.cm-table-wrap')).toHaveCSS('overflow-y','hidden')
})
