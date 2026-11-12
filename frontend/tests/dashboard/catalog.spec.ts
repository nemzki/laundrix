import { expect,test,type Page } from '@playwright/test'
import type { CatalogData } from '../../src/catalog/api'

async function login(page:Page,staff=false) {
  await page.goto('/auth/login');if(staff)await page.getByRole('tab',{name:'Staff',exact:true}).click()
  await page.locator(staff?'#staff-identifier':'#admin-identifier').fill(staff?'staff@example.test':'browseradmin')
  await page.locator(staff?'#staff-password':'#admin-password').fill('Browser-Test-Password!42')
  await page.locator(`form[data-auth-form=${staff?'staff':'admin'}] button[type=submit]`).click();await expect(page).toHaveURL(/dashboard/)
}
async function ready(page:Page){await expect(page.locator('#laundrix-catalog')).toHaveAttribute('data-ready','true')}
async function data(page:Page):Promise<CatalogData> {
  const response=await page.request.get('/admin/services/')
  expect(response.status()).toBe(200)
  return page.evaluate(html=>JSON.parse(new DOMParser().parseFromString(html,'text/html').querySelector('#laundrix-catalog-data')!.textContent!),await response.text())
}
const row=(page:Page,key:string)=>page.locator(`[data-catalog-row="${key}"]`)
const editor=(page:Page)=>page.locator('.catalog-dialog')
async function save(page:Page){await editor(page).getByRole('button',{name:'Save Changes',exact:true}).click();await expect(editor(page)).toHaveCount(0)}

test('catalog starts with the redesigned skeleton and no legacy UI while its bundle is delayed',async({page})=>{
 await login(page);let release!:()=>void;let started!:()=>void;const bundleStarted=new Promise<void>(resolve=>{started=resolve});const bundleReleased=new Promise<void>(resolve=>{release=resolve})
 await page.route('**/react-catalog/catalog.js',async route=>{started();await bundleReleased;await route.continue()})
 await page.goto('/admin/services/',{waitUntil:'commit'});await bundleStarted
 await expect(page.locator('.catalog-boot-skeleton')).toBeVisible();await expect(page.locator('[data-catalog-fallback],#catalog-action-fallback')).toHaveCount(0);await expect(page.locator('.grid-stats,.search-bar,.table-wrap')).toHaveCount(0)
 release();await ready(page);await expect(page.locator('[data-catalog-row]')).toHaveCount((await data(page)).rows.length)
 await expect(page.locator('#catalog-action-react .catalog-boot-action')).toHaveCount(0);await expect(page.locator('#catalog-summary-react .catalog-boot-summary')).toHaveCount(0);await expect(page.locator('#catalog-action-react button')).toHaveCount(1)
})

for(const width of [320,768,1440])test(`React catalog, real categories and preserved form ${width}px`,async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
  await page.setViewportSize({width,height:900});await login(page);await page.goto('/admin/services/');await ready(page)
  const original=await data(page),services=original.rows.filter(item=>item.kind==='services')
  const dark=await page.locator('html').getAttribute('data-lx-theme')==='dark'
  const strip=page.getByRole('tablist',{name:'Catalog modules'})
  const tabs=strip.getByRole('tab'),boxes=await tabs.evaluateAll(nodes=>nodes.map(node=>node.getBoundingClientRect().top))
  expect(new Set(boxes).size).toBe(1)
  await expect(strip).toHaveCSS('overflow-y','hidden')
  const inactive=strip.getByRole('tab',{name:/^Services /})
  await expect(inactive).toHaveCSS('background-color','rgba(0, 0, 0, 0)')
  await inactive.hover();await expect(inactive).toHaveCSS('background-color',dark?'rgb(24, 34, 53)':'rgb(248, 250, 252)')
  await inactive.focus();await page.keyboard.press('ArrowRight');await expect(strip.getByRole('tab',{name:/^Packages /})).toBeFocused();await page.keyboard.press('ArrowLeft');await expect(inactive).toBeFocused();await expect(inactive).toHaveCSS('box-shadow',`${dark?'rgb(52, 120, 246)':'rgb(59, 130, 246)'} 0px 0px 0px 1px inset`)
  await page.keyboard.press('End');await expect(strip.getByRole('tab',{name:/^Add-ons /})).toBeFocused()
  await strip.getByRole('tab',{name:/^All /}).click()
  await expect(strip.getByRole('tab',{name:/^All /})).toHaveCSS('background-color',dark?'rgb(37, 50, 72)':'rgb(241, 245, 249)')

  await expect(page.getByRole('button',{name:'Refresh',exact:true})).toHaveCount(0)
  const contrast=await page.locator('#laundrix-catalog [data-slot=badge]').evaluateAll(nodes=>{
    const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d')!
    function luminance(color:string){ctx.clearRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);const rgb=Array.from(ctx.getImageData(0,0,1,1).data).slice(0,3).map(v=>{const n=v/255;return n<=0.04045?n/12.92:((n+0.055)/1.055)**2.4});return rgb[0]*0.2126+rgb[1]*0.7152+rgb[2]*0.0722}
    return nodes.map(node=>{const style=getComputedStyle(node),a=luminance(style.color),b=luminance(style.backgroundColor);return {variant:node.getAttribute('data-variant'),ratio:(Math.max(a,b)+0.05)/(Math.min(a,b)+0.05)}})
  })
  expect(new Set(contrast.map(item=>item.variant))).toEqual(new Set(['services','packages','addons']))
  for(const badge of contrast) expect(badge.ratio).toBeGreaterThanOrEqual(4.5)

  await expect(page.locator('[data-catalog-row]')).toHaveCount(original.rows.length)
  const allKeys=await page.locator('[data-catalog-row]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('data-catalog-row')))
  expect(new Set(allKeys).size).toBe(original.rows.length)
  await page.locator('#catalog-action-react').getByRole('button').click()
  await expect(page.getByRole('menuitem')).toHaveCount(0)
  await expect(editor(page).getByRole('heading',{name:'Add Service',exact:true})).toBeVisible()
  await expect(editor(page).getByLabel('Service Name',{exact:true})).toBeVisible()
  await expect(editor(page).getByText('Price changes apply to new orders only.',{exact:true})).toBeVisible()
  await expect(editor(page).getByRole('textbox',{name:'Category',exact:true})).toHaveAttribute('maxlength','80')
  await expect(editor(page).getByRole('textbox',{name:'Category',exact:true})).toHaveAttribute('required','')
  await expect(editor(page).getByRole('combobox',{name:'Category',exact:true})).toHaveCount(0)
  await expect(editor(page).getByLabel('Pricing Unit',{exact:true})).toHaveText('Per Load')
  await expect(editor(page).getByLabel('Price',{exact:true})).toHaveAttribute('placeholder','0.00')
  await expect(editor(page).locator('.catalog-unit-suffix')).toHaveText('/ load')
  const options=editor(page).locator('.catalog-service-options .catalog-field')
  const positions=await options.evaluateAll(nodes=>nodes.map(node=>node.getBoundingClientRect().top))
  expect(positions[0]===positions[1]).toBe(width>=480)
  const addBounds=(await editor(page).boundingBox())!
  expect(addBounds.width).toBeLessThanOrEqual(Math.min(540,width-32))
  expect(addBounds.y).toBeGreaterThanOrEqual(0)
  expect(addBounds.y+addBounds.height).toBeLessThanOrEqual(900)
  await expect(editor(page).getByRole('button',{name:'Add Service',exact:true})).toBeVisible()
  await page.screenshot({path:`test-results/dashboard/catalog-${width}-add.png`})

  await editor(page).getByRole('button',{name:'Cancel',exact:true}).click();await expect(editor(page)).toHaveCount(0)
  await page.locator('#catalog-action-react').getByRole('button',{name:'Add Service',exact:true}).click()
  await editor(page).getByRole('button',{name:'Close',exact:true}).click();await expect(editor(page)).toHaveCount(0)
  await expect(page.locator('#catalog-action-react').getByRole('button')).toBeFocused()
  await page.getByRole('tab',{name:/^Services /}).click()
  await expect(page.locator('#catalog-summary-react')).toHaveText(`${services.filter(s=>s.orderable).length} of ${services.length} services available for new orders.`)
  await expect(page.locator('[data-catalog-fallback]')).toBeHidden()
  await expect(page.locator('#laundrix-catalog [data-slot=table-head]')).toHaveText(['Service','Category','Price','Unit','Available','Action'])
  await expect(page.locator('[data-catalog-row]')).toHaveCount(services.length)
  await expect(page.locator('.catalog-icon svg')).toHaveCount(services.length)
  const search=page.getByRole('searchbox',{name:'Search catalog'})
  await expect(search).toHaveAttribute('placeholder','Search catalog')
  const wrapper=page.locator('.catalog-search')
  await expect(wrapper).toHaveCSS('border-top-width','0px');await expect(wrapper).toHaveCSS('box-shadow','none')
  await expect(wrapper.locator('svg')).toHaveCSS('pointer-events','none')
  const icon=wrapper.locator('svg')
  await expect(wrapper.locator('input')).toHaveCount(1)
  await expect(icon).toHaveCSS('width','16px');await expect(icon).toHaveCSS('height','16px')
  const iconBefore=(await icon.boundingBox())!,inputBefore=(await search.boundingBox())!
  expect(Math.abs((iconBefore.y+iconBefore.height/2)-(inputBefore.y+inputBefore.height/2))).toBeLessThan(1)
  expect(inputBefore.x+36-(iconBefore.x+iconBefore.width)).toBe(8)

  await expect(search).toHaveCSS('height','38px')
  await search.hover();await expect(search).toHaveCSS('box-shadow','none')
  const before=await search.boundingBox();await search.click({position:{x:12,y:18}});await expect(search).toBeFocused();await search.focus();await expect(search).toHaveCSS('outline-style','none');await expect(search).toHaveCSS('border-top-width','1px');expect(await search.boundingBox()).toEqual(before)
  await search.fill('Wash');expect(await icon.boundingBox()).toEqual(iconBefore);expect(await search.boundingBox()).toEqual(before);await expect(page.locator('[data-catalog-row]')).toHaveCount(1)
  await row(page,`services-${services.find(s=>s.code==='wash')!.id}`).getByRole('button',{name:'Edit',exact:true}).click()
  await expect(editor(page).getByLabel('Name',{exact:true})).toHaveValue('Wash')
  await expect(editor(page).getByLabel('Category',{exact:true})).toBeVisible()
  await editor(page).getByLabel('Pricing Unit',{exact:true}).click()
  await expect(page.getByRole('option')).toHaveText(['Not set (cannot be ordered)','Per Load','Per Kilogram','Per Piece'])
  await page.getByRole('option',{name:'Per Load',exact:true}).click()
  await editor(page).locator('summary').click()
  await expect(editor(page).getByLabel('Code (Permanent)',{exact:true})).toHaveValue('wash')
  const footer=(await editor(page).locator('.catalog-editor-footer').boundingBox())!
  expect(footer.y+footer.height).toBeLessThanOrEqual(900)
  await page.screenshot({path:`test-results/dashboard/catalog-${width}-edit.png`,fullPage:true})
  await editor(page).getByRole('button',{name:'Cancel',exact:true}).click();await expect(editor(page)).toHaveCount(0)
  await expect(search).toHaveValue('Wash');await search.fill('');await page.getByRole('tab',{name:/Packages/}).click()
  await expect(page.locator('[data-catalog-row]')).toHaveCount(original.rows.filter(item=>item.kind==='packages').length)
  const category=original.rows.find(item=>item.kind==='packages')!.category
  await page.getByRole('searchbox',{name:'Search catalog'}).fill(category)
  await expect(page.locator('[data-catalog-row]')).toHaveCount(original.rows.filter(item=>item.kind==='packages' && item.category===category).length)
  await page.getByRole('searchbox',{name:'Search catalog'}).fill('');await page.getByRole('tab',{name:/Add-ons/}).click();await expect(page.locator('[data-catalog-row]')).toHaveCount(original.rows.filter(item=>item.kind==='addons').length)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  expect(errors).toEqual([])
})

test('service add/edit, server errors, availability and historical pricing integrity',async({page})=>{
  test.setTimeout(90000);await login(page);await page.goto('/admin/services/');await ready(page)
  await page.getByRole('tab',{name:/^Services /}).click()
  const original=await data(page),wash=original.rows.find(item=>item.kind==='services' && item.code==='wash')!
  const list=await page.request.get('/orders/?q=Customer%2000')
  const reference=await page.evaluate(html=>new DOMParser().parseFromString(html,'text/html').querySelector('.mo-rows [data-ref]')!.getAttribute('data-ref')!,await list.text())
  const historical=await (await page.request.get(`/orders/${reference}`)).text()
  const oldSummary=await page.evaluate(html=>JSON.parse(new DOMParser().parseFromString(html,'text/html').querySelector('#order-summary-data')!.textContent!),historical)
  await row(page,`services-${wash.id}`).getByRole('button',{name:'Edit',exact:true}).click()
  await editor(page).getByLabel('Price (PHP)',{exact:true}).fill('91.25');await save(page)
  expect((await data(page)).rows.find(item=>item.kind==='services' && item.id===wash.id)!.price).toContain('91.25')
  const saved=await (await page.request.get(`/orders/${reference}`)).text()
  const newSummary=await page.evaluate(html=>JSON.parse(new DOMParser().parseFromString(html,'text/html').querySelector('#order-summary-data')!.textContent!),saved)
  expect([newSummary.total,newSummary.paid,newSummary.balance]).toEqual([oldSummary.total,oldSummary.paid,oldSummary.balance])
  await row(page,`services-${wash.id}`).getByRole('switch').click();await page.getByRole('button',{name:'Disable entry',exact:true}).click()
  await expect(row(page,`services-${wash.id}`).getByRole('switch')).not.toBeChecked()
  const wizard=await page.request.get('/orders/new');expect(await wizard.text()).not.toContain(`data-code="wash"`)
  await row(page,`services-${wash.id}`).getByRole('switch').click();await expect(row(page,`services-${wash.id}`).getByRole('switch')).toBeChecked()
  const quote=await page.request.post('/orders/new/quote',{headers:{'X-CSRFToken':original.csrf},data:{items:[{kind:'service',id:wash.id,quantity:'1'}],extras:[]}})
  expect((await quote.json()).total_raw).toBe('91.25')
  // Restore the original price through the same live edit form, not a DB shortcut.
  await row(page,`services-${wash.id}`).getByRole('button',{name:'Edit',exact:true}).click();await editor(page).getByLabel('Price (PHP)',{exact:true}).fill('80.00');await save(page)
  await page.locator('#catalog-action-react').getByRole('button').click()
  await editor(page).getByLabel('Service Name',{exact:true}).fill('Catalog Browser QA')
  await editor(page).getByLabel('Code',{exact:true}).fill('catalog_browser_qa')
  await editor(page).getByLabel('Price',{exact:true}).fill('12.50')
  await editor(page).getByLabel('Pricing Unit',{exact:true}).click();await page.getByRole('option',{name:'Per Piece',exact:true}).click()
  await editor(page).getByRole('textbox',{name:'Category',exact:true}).fill('Browser QA category')
  await editor(page).locator('summary').click();await editor(page).getByLabel('Image Path (Optional)',{exact:true}).fill('https://invalid.example/image.png')
  await editor(page).getByRole('button',{name:'Add Service',exact:true}).click();await expect(editor(page).getByRole('alert').first()).toContainText('local path')
  await expect(editor(page).getByLabel('Service Name',{exact:true})).toHaveValue('Catalog Browser QA')
  await editor(page).getByLabel('Image Path (Optional)',{exact:true}).fill('')
  await editor(page).getByRole('button',{name:'Add Service',exact:true}).click();await expect(editor(page)).toHaveCount(0)
  const created=(await data(page)).rows.find(item=>item.code==='catalog_browser_qa')!
  expect(created.category).toBe('Browser QA category');expect(created.unit).toBe('per piece')
  expect(await (await page.request.get('/orders/new')).text()).toContain('Catalog Browser QA')
})

test('package and add-on forms preserve original separate fields and validation',async({page})=>{
  await login(page);await page.goto('/admin/services/?tab=packages');await ready(page)
  const original=await data(page),pkg=original.rows.find(item=>item.kind==='packages')!
  await row(page,`packages-${pkg.id}`).getByRole('button',{name:'Edit',exact:true}).click()
  for(const name of ['Package Name','Description','Size Label (Optional)','Measured By','Minimum','Maximum']) await expect(editor(page).getByLabel(name,{exact:true})).toBeVisible()
  await expect(editor(page).locator('[name=covers_codes]')).toHaveCount(original.rows.filter(item=>item.kind==='services').length)
  await save(page);await page.getByRole('tab',{name:/Add-ons/}).click()
  const addon=original.rows.find(item=>item.kind==='addons')!
  await row(page,`addons-${addon.id}`).getByRole('button',{name:'Edit',exact:true}).click()
  await expect(editor(page).locator('[name=is_chargeable]')).toBeChecked();await expect(editor(page).locator('[name=allow_customer_supplied]')).toBeChecked()
  await editor(page).locator('[name=is_chargeable]').uncheck();await editor(page).locator('[name=allow_customer_supplied]').uncheck()
  await editor(page).getByRole('button',{name:'Save Changes',exact:true}).click();await expect(editor(page).getByRole('alert').first()).toContainText('chargeable, customer-suppliable')
  await editor(page).locator('[name=is_chargeable]').check();await editor(page).locator('[name=allow_customer_supplied]').check();await save(page)
})

test('fallback pages, form-load retry and backend Staff authorization',async({page,browser})=>{
  await login(page);await page.goto('/admin/services/');await ready(page)
  let fail=true
  await page.route('**/services/*/edit',route=>route.request().method()==='GET' && fail ? (fail=false,route.abort('failed')) : route.continue())
  await page.locator('[data-catalog-row]').first().getByRole('button',{name:'Edit',exact:true}).click()
  await editor(page).getByRole('button',{name:'Retry',exact:true}).click();await expect(editor(page).getByLabel('Name',{exact:true})).toBeVisible()
  const context=await browser.newContext({storageState:await page.context().storageState(),javaScriptEnabled:false})
  try{const native=await context.newPage();await native.goto('http://127.0.0.1:8771/admin/services/');await expect(native.locator('.catalog-boot-skeleton')).toBeVisible();expect((await native.request.get('/admin/services/services/new')).status()).toBe(200)}finally{await context.close()}
  const staffContext=await browser.newContext(),staff=await staffContext.newPage()
  try{await login(staff,true);expect((await staff.request.get('/admin/services/')).status()).toBe(403)}finally{await staffContext.close()}
})

test('all four module tabs, scoped search and contextual package/add-on persistence',async({page})=>{
  await login(page);await page.goto('/admin/services/?tab=all');await ready(page)
  const original=await data(page)
  const names={all:'All',services:'Services',packages:'Packages',addons:'Add-ons'}
  for(const module of ['all','services','packages','addons'] as const) {
    const expected=module==='all' ? original.rows : original.rows.filter(item=>item.kind===module)
    const tab=page.getByRole('tab',{name:`${names[module]} ${expected.length}`,exact:true})
    await tab.click();await expect(tab).toHaveAttribute('aria-selected','true')
    await expect(page.locator('[data-catalog-row]')).toHaveCount(expected.length)
    const keys=await page.locator('[data-catalog-row]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('data-catalog-row')))
    expect(new Set(keys).size).toBe(keys.length)
    if(module!=='all') expect(keys.every(key=>key!.startsWith(`${module}-`))).toBe(true)
    const search=page.getByRole('searchbox',{name:'Search catalog'})
    await search.fill('no matching catalog item');await expect(page.locator('[data-catalog-row]')).toHaveCount(0)
    await search.fill('');await expect(page.locator('[data-catalog-row]')).toHaveCount(expected.length)
    if(module!=='all') await expect(page.locator('#catalog-action-react').getByRole('button')).toHaveText(`Add ${module==='services' ? 'Service' : module==='packages' ? 'Package':'Add-on'}`)
  }
  await page.getByRole('tab',{name:/^All /}).click()
  await page.getByRole('tab',{name:/^Packages /}).click();await page.locator('#catalog-action-react').getByRole('button',{name:'Add Package',exact:true}).click()
  await editor(page).getByLabel('Package Name',{exact:true}).fill('Module Tabs QA Package')
  await editor(page).getByLabel('Custom category').fill('Module Tabs QA')
  await editor(page).getByLabel('Description',{exact:true}).fill('QA weight range')
  await editor(page).getByLabel('Minimum',{exact:true}).fill('3');await editor(page).getByLabel('Maximum',{exact:true}).fill('5')
  await editor(page).getByLabel('Price (PHP)',{exact:true}).fill('33.00')
  await editor(page).getByRole('button',{name:'Add Package',exact:true}).click();await expect(editor(page)).toHaveCount(0)
  await expect(page.getByRole('tab',{name:/^Packages /})).toHaveAttribute('aria-selected','true')
  await page.getByRole('tab',{name:/^All /}).click()
  await expect(page.locator('[data-catalog-row]')).toHaveCount(original.rows.length+1)
  await page.getByRole('tab',{name:/^Add-ons /}).click();await page.locator('#catalog-action-react').getByRole('button',{name:'Add Add-on',exact:true}).click()
  await editor(page).getByLabel('Name',{exact:true}).fill('Module Tabs QA Extra');await editor(page).getByLabel('Code',{exact:true}).fill('module_tabs_qa_extra')
  await editor(page).getByLabel('Price per Unit (PHP)',{exact:true}).fill('7.50')
  await editor(page).locator('[name=allow_customer_supplied]').uncheck()
  await editor(page).getByRole('button',{name:'Add Add-on',exact:true}).click();await expect(editor(page)).toHaveCount(0)
  await page.getByRole('tab',{name:/^All /}).click()
  await expect(page.locator('[data-catalog-row]')).toHaveCount(original.rows.length+2)
  const saved=await data(page),pkg=saved.rows.find(item=>item.name==='Module Tabs QA Package')!,extra=saved.rows.find(item=>item.code==='module_tabs_qa_extra')!
  expect(pkg.kind).toBe('packages');expect(extra.kind).toBe('addons');expect(extra.customerSupplied).toBe(false);expect(extra.price).toContain('7.50')
  await row(page,`packages-${pkg.id}`).getByRole('button',{name:'Edit',exact:true}).click()
  await expect(editor(page).getByLabel('Measured By',{exact:true})).toBeVisible();await expect(editor(page).locator('[name=pricing_unit]')).toHaveCount(0)
  await editor(page).getByLabel('Price (PHP)',{exact:true}).fill('34.75');await save(page)
  expect((await data(page)).rows.find(item=>item.kind==='packages' && item.id===pkg.id)!.price).toContain('34.75')
})

test('rejected availability remains unchanged until a real backend confirmation',async({page})=>{
  await login(page);await page.goto('/admin/services/?tab=services');await ready(page)
  const saved=(await data(page)).rows.find(item=>item.kind==='services' && item.active)!
  await page.route('**/services/*/toggle',route=>route.fulfill({status:503,body:'Unavailable'}))
  await row(page,`services-${saved.id}`).getByRole('switch').click();await page.getByRole('button',{name:'Disable entry',exact:true}).click()
  await expect(page.locator('[role=alert]')).toContainText('Availability could not be confirmed')
  await expect(row(page,`services-${saved.id}`).getByRole('switch')).toBeChecked()
  expect((await data(page)).rows.find(item=>item.kind==='services' && item.id===saved.id)!.active).toBe(true)
})
