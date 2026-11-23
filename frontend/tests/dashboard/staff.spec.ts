import { expect,test,type Page } from '@playwright/test'
async function login(page:Page){await page.goto('/auth/login');await page.locator('#identifier').fill('browseradmin');await page.locator('#password').fill('Browser-Test-Password!42');await page.locator('form[data-auth-form] button[type=submit]').click();await expect(page).toHaveURL(/dashboard/)}
async function ready(page:Page){await expect(page.locator('#laundrix-staff')).toHaveAttribute('data-ready','true')}
async function list(page:Page,query=''){const response=await page.request.get('/admin/staff/'+query);expect(response.status()).toBe(200);const html=await response.text();return page.evaluate(text=>JSON.parse(new DOMParser().parseFromString(text,'text/html').querySelector('#laundrix-staff-data')!.textContent!),html)}
const dialog=(page:Page)=>page.locator('.staff-dialog[data-state=open]')
async function viewFirst(page:Page){await page.locator('[data-staff-row]').first().getByRole('button',{name:/Actions for/}).click();await page.getByRole('menuitem',{name:'View Details',exact:true}).click();await expect(page.locator('.staff-sheet')).toBeVisible();await expect(page.locator('.staff-facts')).toBeVisible()}
for(const width of [320,768,1440])test(`staff table, Add Dialog and details Sheet ${width}px`,async({page})=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));await page.setViewportSize({width,height:900});await login(page);await page.goto('/admin/staff/');await ready(page)
 const original=await list(page);await expect(page.locator('[data-staff-row]')).toHaveCount(original.rows.length)
 await expect(page.getByRole('heading',{name:'Staff Management',exact:true})).toBeVisible();await expect(page.getByText('Manage staff accounts, access, and verification.',{exact:true})).toBeVisible()
 await expect(page.locator('#staff-action-react .staff-boot-action')).toHaveCount(0)
 await expect(page.getByRole('tab',{name:'All '+original.counts.total,exact:true})).toHaveAttribute('aria-selected','true')
 for(const label of [/^Pending verification /i,/^Pending approval /i,/^Active \d+$/i,/^Suspended /i,/^Rejected /i,/^Inactive /i])await expect(page.getByRole('tab',{name:label})).toBeVisible()
 await page.locator('#staff-action-react').getByRole('button',{name:'Add Staff',exact:true}).click();await expect(dialog(page).getByRole('heading',{name:'Add Staff Account'})).toBeVisible()
 await expect(dialog(page).getByText("Enter the staff member's information to generate their enrollment link.",{exact:true})).toBeVisible()
 await expect(dialog(page).getByRole('textbox',{name:'Full Name',exact:true})).toBeVisible();await expect(dialog(page).getByRole('textbox',{name:'Full Name',exact:true})).toHaveAttribute('required','');await expect(dialog(page).getByRole('textbox',{name:'Email',exact:true})).toBeVisible();await expect(dialog(page).getByRole('textbox',{name:'Email',exact:true})).toHaveAttribute('required','')
 await expect(dialog(page)).toHaveCSS('padding','0px')
 await expect(dialog(page).locator('.staff-form-footer')).toHaveCSS('padding','14px 20px');await expect(dialog(page).locator('.staff-form-footer')).toHaveCSS('margin','0px')
 await expect(dialog(page).getByRole('button',{name:'Add and Generate Link',exact:true})).toBeVisible();await expect(dialog(page).getByText('Role',{exact:true})).toHaveCount(0)
 await expect(dialog(page).locator('.staff-required')).toHaveCount(2);await expect(dialog(page).locator('input:not([type=hidden])')).toHaveCount(2);await expect(dialog(page).getByRole('combobox')).toHaveCount(0)
 const bounds=(await dialog(page).boundingBox())!;expect(bounds.x).toBeGreaterThanOrEqual(0);expect(bounds.x+bounds.width).toBeLessThanOrEqual(width);expect(bounds.y+bounds.height).toBeLessThanOrEqual(900)
 await page.screenshot({path:`test-results/dashboard/staff-${width}-add.png`})
 await dialog(page).getByRole('button',{name:'Cancel',exact:true}).click();await expect(page.locator('.staff-dialog')).toHaveCount(0);await expect(page.locator('#staff-action-react button')).toBeFocused()
 await page.locator('#staff-action-react button').click();await dialog(page).getByRole('button',{name:'Close',exact:true}).click();await expect(page.locator('.staff-dialog')).toHaveCount(0)
 await viewFirst(page);await expect(page.locator('.staff-sheet')).toContainText(original.rows[0].email);await expect(page.locator('.staff-sheet')).toContainText('Identity Verification');await expect(page.locator('.staff-sheet').getByRole('button',{name:'Edit account'})).toHaveCount(0)
 await expect.poll(async()=>{const sheet=(await page.locator('.staff-sheet').boundingBox())!;return Math.abs(sheet.x+sheet.width-width)}).toBeLessThan(1)
 await page.screenshot({path:`test-results/dashboard/staff-${width}-drawer.png`});await page.keyboard.press('Escape');await expect(page.locator('.staff-sheet')).toHaveCount(0)
 const search=page.getByRole('searchbox',{name:'Search staff'});await search.fill('staff@example.test');await expect(page.locator('[data-staff-row]')).toHaveCount(1);await search.fill('no matching account');await expect(page.getByText('No staff match your filters.',{exact:true})).toBeVisible();await page.getByRole('button',{name:'Clear Filters',exact:true}).click();await expect(page.locator('[data-staff-row]')).toHaveCount(original.rows.length)
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);expect(errors).toEqual([])
})
test('six Staff status badges use distinct semantic colors',async({page})=>{
 await login(page);await page.goto('/admin/staff/');await ready(page)
 const colors=await page.evaluate(()=>{const root=document.createElement('div');root.className='lx-react lx-staff';root.style.position='absolute';root.style.left='-10000px';const statuses=['pending_verification','pending_approval','active','suspended','rejected','deactivated'];for(const status of statuses){const badge=document.createElement('span');badge.className='staff-status';badge.dataset.accountStatus=status;root.append(badge)}document.body.append(root);const values=Array.from(root.children).map(element=>getComputedStyle(element).backgroundColor+'|'+getComputedStyle(element).color);root.remove();return values})
 expect(new Set(colors).size).toBe(6)
})

for (const width of [320,768,1440]) test(`staff polish wraps filters and preserves the Admin container at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:1000});await login(page);await page.goto('/admin/staff/');await ready(page)
 const dark=await page.locator('html').getAttribute('data-lx-theme')==='dark'
 const labels=['All','Pending Verification','Pending Approval','Active','Suspended','Rejected','Inactive']
 const tabs=page.getByRole('tablist',{name:'Account status'}).getByRole('tab')
 const initial=await list(page)
 expect(await tabs.evaluateAll(nodes=>nodes.map(node=>node.textContent?.replace(/\d+$/,'').trim()))).toEqual(labels)
 const boxes=await tabs.evaluateAll(nodes=>nodes.map(node=>({top:node.getBoundingClientRect().top,height:node.getBoundingClientRect().height})))
 for(const box of boxes)expect(box.height).toBe(36)
 if(width<1000)expect(new Set(boxes.map(box=>box.top)).size).toBeGreaterThan(1)
 await expect(page.locator('.staff-tabs')).toHaveCSS('flex-wrap','wrap')
 await expect(tabs.first()).toHaveCSS('background-color',dark?'rgb(23, 46, 80)':'rgb(234, 244, 255)')
 const content=await page.locator('main.content').boundingBox()
 await page.getByRole('searchbox',{name:'Search staff'}).fill('staff@example.test')
 await expect(page.locator('[data-staff-row]')).toHaveCount(1)
 await page.locator('#staff-sort').selectOption('oldest')
 await expect(page.locator('.staff-panel')).toHaveAttribute('aria-busy','false')
 for(const control of [page.getByRole('searchbox',{name:'Search staff'}),page.locator('#staff-sort'),page.getByRole('button',{name:'Clear Filters',exact:true})])expect((await control.boundingBox())!.height).toBe(36)
 const search=page.getByRole('searchbox',{name:'Search staff'}),before=await search.boundingBox();await search.focus();expect(await search.boundingBox()).toEqual(before);await expect(search).toHaveCSS('outline-style','none')
 await page.getByRole('button',{name:'Clear Filters',exact:true}).click();await expect(page.locator('.staff-panel')).toHaveAttribute('aria-busy','false')
 await expect(search).toHaveValue('');await expect(page.locator('#staff-sort')).toHaveValue('newest')
 await expect(page.locator('[data-staff-row]')).toHaveCount(initial.rows.length)
 expect(await page.locator('main.content').boundingBox()).toEqual(content)
 await expect(page.locator('.staff-table')).toHaveCSS('table-layout','fixed')
 await expect(page.locator('[data-slot=table-head]').first()).toHaveCSS('padding','10px 16px');await expect(page.locator('[data-slot=table-head]').first()).toHaveCSS('font-size','13px')
 await expect(page.locator('[data-slot=table-cell]').first()).toHaveCSS('padding','10px 16px');await expect(page.locator('.staff-pagination')).toHaveCSS('padding','14px 16px')
 const wrap=page.locator('[data-slot=table-container]');await expect(wrap).toHaveCSS('overflow-y','hidden')
 expect(await wrap.evaluate(el=>el.scrollHeight<=el.clientHeight)).toBe(true)
 // Long backend-supported names/emails must wrap inside their existing column.
 await page.locator('.staff-person strong').first().evaluate(el=>el.textContent='Long Staff Name '.repeat(9))
 await page.locator('.staff-person p').first().evaluate(el=>el.textContent='long.email.address.'.repeat(8)+'@example.test')
 expect(await page.locator('.staff-person').first().evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true)
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
 await page.screenshot({path:`test-results/dashboard/staff-polish-${dark?'dark':'light'}-${width}.png`,fullPage:true})
})

test('every Staff status filter keeps its backend value and actual counts',async({page})=>{
 await login(page);await page.goto('/admin/staff/');await ready(page)
 const values=['','pending_verification','pending_approval','active','suspended','rejected','deactivated']
 const labels=['All','Pending Verification','Pending Approval','Active','Suspended','Rejected','Inactive']
 for(let i=0;i<values.length;i++){
  const expected=await list(page,values[i]?'?status='+values[i]:'')
  const tab=page.getByRole('tab',{name:new RegExp('^'+labels[i]+' \\d+$')})
  expect(await tab.locator('.staff-tab-count').innerText()).toBe(String(values[i]?expected.counts[values[i]]:expected.counts.total))
  await tab.click();await expect(page.locator('.staff-panel')).toHaveAttribute('aria-busy','false')
  await expect(tab).toHaveAttribute('aria-selected','true')
  expect(new URL(page.url()).searchParams.get('status')||'').toBe(values[i])
  expect(await page.locator('[data-staff-row]').evaluateAll(nodes=>nodes.map(node=>Number(node.getAttribute('data-staff-row'))))).toEqual(expected.rows.map((row:{id:number})=>row.id))
 }
})
test('actual creation, backend validation, one-time link and native fallback',async({page,browser})=>{
 await login(page);await page.goto('/admin/staff/');await ready(page);await page.locator('#staff-action-react button').click()
 await page.setViewportSize({width:390,height:780})
 await dialog(page).getByRole('textbox',{name:'Full Name',exact:true}).fill('New Staff QA');await dialog(page).getByRole('textbox',{name:'Email',exact:true}).fill('staff@example.test');await dialog(page).getByRole('button',{name:'Add and Generate Link',exact:true}).click();await expect(dialog(page).getByRole('alert')).toBeVisible();await expect(dialog(page).getByRole('textbox',{name:'Full Name',exact:true})).toHaveValue('New Staff QA')
 await dialog(page).getByRole('textbox',{name:'Email',exact:true}).fill('staff-ui-qa@example.test');let posts=0;page.on('request',request=>{if(request.method()==='POST'&&request.url().endsWith('/admin/staff/new'))posts++})
 await dialog(page).getByRole('button',{name:'Add and Generate Link',exact:true}).click();await expect(dialog(page).getByRole('heading',{name:'Enrollment Link Generated',exact:true})).toBeVisible();expect(posts).toBe(1)
 await expect(dialog(page).getByText('Link Ready to Share',{exact:true})).toBeVisible();await expect(dialog(page).locator('.staff-link-success')).toContainText('New Staff QA')
 await expect(dialog(page).locator('#staff-enrollment')).toHaveValue(/\/staff\/enroll\//);await expect(dialog(page).locator('.staff-expiration')).toContainText(/^Expires .+/);await expect(dialog(page).locator('.staff-enrollment-next')).toContainText('Pending approval')
 await page.screenshot({path:'test-results/dashboard/staff-enrollment-link-390.png'})
 await page.context().grantPermissions(['clipboard-read','clipboard-write']);await dialog(page).getByRole('button',{name:'Copy Link',exact:true}).click();await expect(dialog(page).getByRole('button',{name:'Copied',exact:true})).toBeVisible();expect(await page.evaluate(()=>navigator.clipboard.readText())).toBe(await dialog(page).locator('#staff-enrollment').inputValue())
 const enrollmentBounds=(await dialog(page).boundingBox())!;expect(enrollmentBounds.width).toBeLessThanOrEqual(390);expect(enrollmentBounds.height).toBeLessThan(780);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
 await expect(dialog(page).getByRole('link',{name:'View Account',exact:true})).toHaveAttribute('href',/\/admin\/staff\/\d+/);await dialog(page).getByRole('button',{name:'Done',exact:true}).click()
 const saved=await list(page,'?q=staff-ui-qa');expect(saved.total).toBe(1);expect(saved.rows[0].status).toBe('pending_verification');expect(saved.rows[0].role).toBe('staff')
 await page.getByRole('searchbox',{name:'Search staff'}).fill('staff-ui-qa');await expect(page.locator('[data-staff-row]')).toHaveCount(1);await expect(page.locator('[data-staff-row]')).toContainText('Pending Verification')
 const native=await browser.newContext({storageState:await page.context().storageState(),javaScriptEnabled:false});try{const tab=await native.newPage();await tab.goto('http://127.0.0.1:8771/admin/staff/');await expect(tab.locator('.staff-boot-skeleton')).toBeVisible();expect((await tab.request.get('/admin/staff/new')).status()).toBe(200)}finally{await native.close()}
})
test('server-backed filters, sorts, pagination and authorization',async({page,browser})=>{
 await login(page);await page.goto('/admin/staff/');await ready(page)
 const csrf=await page.request.get('/admin/staff/new');const token=await page.evaluate(html=>new DOMParser().parseFromString(html,'text/html').querySelector<HTMLInputElement>('[name=csrf_token]')!.value,await csrf.text())
 for(let i=0;i<16;i++){const response=await page.request.post('/admin/staff/new',{form:{csrf_token:token,full_name:`Pagination Staff ${i}`,email:`staff-pagination-${i}@example.test`}});expect(response.status()).toBe(200)}
 await page.reload();await ready(page);const initial=await list(page);expect(initial.total).toBeGreaterThan(15);await expect(page.locator('[data-staff-row]')).toHaveCount(15)
 const first=await page.locator('[data-staff-row]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('data-staff-row')));await page.getByRole('button',{name:'Next',exact:true}).click();await expect(page.getByText('Page 2 of 2',{exact:true})).toBeVisible();const second=await page.locator('[data-staff-row]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('data-staff-row')));expect(second.some(id=>first.includes(id))).toBe(false)
 await page.getByRole('tab',{name:/^Pending Verification /}).click();await expect(page.locator('.staff-pagination')).toContainText('Page 1');await expect(page.locator('[data-staff-row]')).not.toContainText(['Active'])
 await page.getByRole('searchbox',{name:'Search staff'}).fill('staff-pagination-15@');await expect(page.locator('[data-staff-row]')).toHaveCount(1);await expect(page.locator('[data-staff-row]')).toContainText('Pagination Staff 15')
 await page.locator('#staff-sort').selectOption('name');await expect(page.locator('[data-staff-row]')).toHaveCount(1);await page.getByRole('button',{name:'Clear Filters',exact:true}).click();await expect(page.getByRole('tab',{name:/^All /})).toHaveAttribute('aria-selected','true')
 const staff=await browser.newContext();try{const tab=await staff.newPage();await tab.goto('http://127.0.0.1:8771/auth/login');await tab.locator('#identifier').fill('staff@example.test');await tab.locator('#password').fill('Browser-Test-Password!42');await tab.locator('form[data-auth-form] button[type=submit]').click();await expect(tab).toHaveURL(/dashboard/);expect((await tab.request.get('/admin/staff/')).status()).toBe(403);expect((await tab.request.post('/admin/staff/new',{form:{}})).status()).toBeGreaterThanOrEqual(400)}finally{await staff.close()}
})
test('React-shaped Staff Management skeleton is initial and remains during delayed bundle load',async({page})=>{
 await login(page);let release!:()=>void;let started!:()=>void;const bundleStarted=new Promise<void>(resolve=>{started=resolve});const bundleReleased=new Promise<void>(resolve=>{release=resolve})
 await page.route('**/react-staff/staff.js',async route=>{started();await bundleReleased;await route.continue()})
 await page.getByRole('link',{name:'Staff Management'}).first().click({noWaitAfter:true});await expect(page).toHaveURL(/\/admin\/staff\/$/);await bundleStarted;const expected=await page.locator('#laundrix-staff-data').evaluate(node=>JSON.parse(node.textContent||'{}').rows.length)
 await expect(page.locator('.staff-boot-skeleton')).toBeVisible();await expect(page.locator('[data-staff-fallback],#staff-action-fallback')).toHaveCount(0);await expect(page.locator('#laundrix-staff')).not.toBeHidden()
 await expect(page.locator('.staff-boot-tabs i')).toHaveCount(7);await expect(page.locator('#staff-action-react')).toHaveCSS('background-color','rgba(0, 0, 0, 0)')
 await expect(page.locator('.grid-stats,.search-bar,.table-wrap')).toHaveCount(0)
 release();await ready(page);await expect(page.locator('[data-staff-row]')).toHaveCount(expected)
 await expect(page.locator('#staff-action-react .staff-boot-action')).toHaveCount(0);await expect(page.locator('#staff-action-react button')).toHaveCount(1)
 await page.keyboard.press('Control+Shift+R');await ready(page);await expect(page.locator('[data-staff-fallback],#staff-action-fallback')).toHaveCount(0);await expect(page.locator('#staff-action-react .staff-boot-action')).toHaveCount(0);await expect(page.locator('#staff-action-react button')).toHaveCount(1)
})
test('original lifecycle action, required reason, saved history and failure feedback',async({page})=>{
 await login(page);await page.goto('/admin/staff/?q=staff@example.test');await ready(page);await viewFirst(page)
 await page.locator('.staff-sheet').getByRole('button',{name:'Suspend Account',exact:true}).click();await expect(dialog(page)).toBeVisible();await dialog(page).getByLabel('Reason (Required)').fill('QA temporary suspension')
 await dialog(page).getByRole('button',{name:'Confirm',exact:true}).click();await expect(page.locator('.staff-dialog')).toHaveCount(0);await expect(page.locator('.staff-sheet .staff-status')).toHaveText('Suspended');await expect(page.locator('.staff-timeline')).toContainText('Staff suspended')
 await page.locator('.staff-sheet').getByRole('button',{name:'Reactivate Account',exact:true}).click();await dialog(page).getByRole('button',{name:'Confirm',exact:true}).click();await expect(page.locator('.staff-dialog')).toHaveCount(0);await expect(page.locator('.staff-sheet .staff-status')).toHaveText('Active');expect((await list(page,'?q=staff@example.test')).rows[0].status).toBe('active')
 await page.keyboard.press('Escape');await expect(page.locator('.staff-sheet')).toHaveCount(0)
 await page.locator('[data-staff-row]').first().getByRole('button',{name:/Actions for/}).click();await page.getByRole('menuitem',{name:'Suspend Account',exact:true}).click();await dialog(page).getByLabel('Reason (Required)').fill('Failure test')
 await page.route('**/admin/staff/*/suspend',route=>route.fulfill({status:503,body:'Unavailable'}));await dialog(page).getByRole('button',{name:'Confirm',exact:true}).click();await expect(dialog(page).getByRole('alert')).toContainText('not confirmed');await expect(dialog(page).getByLabel('Reason (Required)')).toHaveValue('Failure test');expect((await list(page,'?q=staff@example.test')).rows[0].status).toBe('active')
})

test('replacement enrollment link, rejection and deactivation use original saved workflows',async({page})=>{
 await login(page);await page.goto('/admin/staff/');await ready(page);const createResponse=await page.request.get('/admin/staff/new');const token=await page.evaluate(html=>new DOMParser().parseFromString(html,'text/html').querySelector<HTMLInputElement>('[name=csrf_token]')!.value,await createResponse.text());const email=`staff-link-qa-${Date.now()}@example.test`;const created=await page.request.post('/admin/staff/new',{form:{csrf_token:token,full_name:'Staff Link QA',email}});expect(created.status()).toBe(200);await page.goto(`/admin/staff/?q=${encodeURIComponent(email)}`);await ready(page)
 const dark=await page.locator('html').getAttribute('data-lx-theme')==='dark'; const actionTrigger=page.locator('[data-staff-row]').first().getByRole('button',{name:/Actions for/});await actionTrigger.click();const generateLink=page.getByRole('menuitem',{name:'Generate New Link',exact:true}),reject=page.getByRole('menuitem',{name:'Reject Account',exact:true}),deactivate=page.getByRole('menuitem',{name:'Deactivate Account',exact:true});await expect(generateLink).toHaveAttribute('data-variant','default');await expect(reject).toHaveAttribute('data-variant','destructive');await expect(deactivate).toHaveAttribute('data-variant','destructive');await expect(page.locator('[data-slot=dropdown-menu-separator]')).toHaveCount(1);await expect(reject).toHaveCSS('color',dark?'rgb(252, 165, 165)':'rgb(220, 38, 38)');await expect(reject.locator('svg')).toHaveCSS('color',dark?'rgb(252, 165, 165)':'rgb(220, 38, 38)');await reject.hover();await expect(reject).toHaveCSS('background-color',dark?'rgb(59, 32, 44)':'rgb(254, 242, 242)');await page.keyboard.press('Escape');await actionTrigger.focus();await page.keyboard.press('Enter');await expect(generateLink).toBeVisible();await page.keyboard.press('Home');await expect(page.getByRole('menuitem',{name:'View Details',exact:true})).toBeFocused();await page.keyboard.press('ArrowDown');await expect(generateLink).toBeFocused();await page.keyboard.press('ArrowDown');await expect(reject).toBeFocused();await expect(reject).toHaveCSS('outline-style','solid');await page.keyboard.press('Escape');await viewFirst(page)
 await page.locator('.staff-sheet').getByRole('button',{name:'Generate New Link',exact:true}).click();await dialog(page).getByRole('button',{name:'Confirm',exact:true}).click();await expect(dialog(page).getByRole('heading',{name:'Enrollment Link Generated',exact:true})).toBeVisible();await expect(dialog(page).locator('#staff-enrollment')).toHaveValue(/\/staff\/enroll\//);const enrollmentBounds=(await dialog(page).boundingBox())!;expect(enrollmentBounds.width).toBeLessThanOrEqual(520);expect(enrollmentBounds.width).toBeGreaterThanOrEqual(480);expect(enrollmentBounds.height).toBeLessThan(900);await dialog(page).getByRole('button',{name:'Done',exact:true}).click()
 await page.locator('.staff-sheet').getByRole('button',{name:'Reject Account',exact:true}).click();await expect(dialog(page).getByRole('heading',{name:'Reject Account',exact:true})).toBeVisible();await expect(dialog(page).getByText('Are you sure you want to reject this staff account? The staff member will not be able to sign in.',{exact:true})).toBeVisible();await expect(dialog(page).getByText('Staff Link QA',{exact:true})).toBeVisible();const rejectReason=dialog(page).getByLabel('Reason for Rejection *');await expect(rejectReason).toHaveAttribute('rows','3');await expect(rejectReason).toHaveAttribute('name','reason');await expect(rejectReason).toHaveAttribute('placeholder','Enter the reason for rejecting this account...');const rejectBounds=(await dialog(page).boundingBox())!;expect(rejectBounds.width).toBeLessThanOrEqual(480);await rejectReason.fill('   ');await dialog(page).getByRole('button',{name:'Reject Account',exact:true}).click();await expect(dialog(page).getByRole('alert')).toContainText('3 to 255 characters');await expect(dialog(page)).toBeVisible();await rejectReason.fill('QA rejected registration');await dialog(page).getByRole('button',{name:'Reject Account',exact:true}).click();await expect(page.locator('.staff-dialog')).toHaveCount(0);await expect(page.locator('.staff-sheet .staff-status')).toHaveText('Rejected');await expect(page.locator('.staff-facts')).toContainText('None active')
 await page.locator('.staff-sheet').getByRole('button',{name:'Deactivate Account',exact:true}).click();await expect(dialog(page).getByRole('heading',{name:'Deactivate Account',exact:true})).toBeVisible();await expect(dialog(page).locator('.staff-confirm-icon')).toBeVisible();await dialog(page).getByLabel('Reason for Deactivation *').fill('QA offboarding');await dialog(page).getByRole('button',{name:'Deactivate Account',exact:true}).click();await expect(page.locator('.staff-dialog')).toHaveCount(0);await expect(page.locator('.staff-sheet .staff-status')).toHaveText('Inactive');await expect(page.locator('.staff-account-actions')).toContainText('No further actions')
 expect((await list(page,`?q=${encodeURIComponent(email)}`)).rows[0].status).toBe('deactivated')
 await page.keyboard.press('Escape');await page.getByRole('tab',{name:/^Inactive /}).click();await expect(page.locator('[data-staff-row]')).toContainText('Staff Link QA')
})

test('full Staff Details uses the live account, responsive layout and server actions', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await login(page)
  const createForm = await page.request.get('/admin/staff/new')
  const csrf = await page.evaluate(html => new DOMParser().parseFromString(html, 'text/html')
    .querySelector<HTMLInputElement>('[name=csrf_token]')!.value, await createForm.text())
  const fullName = 'Details Workflow QA'
  const email = `staff-detail-${Date.now()}@example.test`
  const created = await page.request.post('/admin/staff/new', { form: { csrf_token: csrf, full_name: fullName, email } })
  expect(created.ok()).toBe(true)
  await page.goto(`/admin/staff/?q=${encodeURIComponent(email)}`)
  await ready(page)
  await viewFirst(page)
  await page.getByRole('link', { name: 'Open Account Page' }).click()
  await ready(page)

  const root = page.locator('#laundrix-staff')
  const accountDetails = page.getByRole('region', { name: 'Account details' })
  const steps = page.getByRole('region', { name: 'Verification progress' }).getByRole('listitem')
  const activity = page.getByRole('heading', { name: 'Recent activity' })
  const nextStep = page.getByRole('heading', { name: 'Send an enrollment link' })
  const danger = page.getByRole('heading', { name: 'Danger zone' })
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(fullName)
  await expect(root.locator('.staff-avatar')).toHaveText('DW')
  await expect(root).toContainText(email)
  await expect(root.locator('.staff-status')).toHaveText('Pending Verification')
  await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toContainText(fullName)
  await expect(page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'Staff Management' })).toHaveAttribute('href', '/admin/staff/')
  await expect(steps).toHaveCount(4)
  await expect(steps.nth(0)).toHaveAttribute('data-step-state', 'Completed')
  await expect(steps.nth(1)).toHaveAttribute('aria-current', 'step')
  await expect(steps.nth(2)).toHaveAttribute('data-step-state', 'Upcoming')
  await expect(steps.nth(3)).toContainText('Never signed in')
  await expect(accountDetails).toContainText('Active until')
  await expect(root).toContainText('Staff created')
  await expect(root.getByRole('button', { name: 'Reject Account' })).toBeHidden()
  await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'dark')

  await page.setViewportSize({ width: 1440, height: 900 })
  expect((await accountDetails.boundingBox())!.y).toBeLessThan((await activity.boundingBox())!.y)
  expect((await nextStep.boundingBox())!.x).toBeGreaterThan((await accountDetails.boundingBox())!.x)
  expect((await danger.boundingBox())!.y).toBeGreaterThan((await nextStep.boundingBox())!.y)
  await page.screenshot({ path: 'test-results/dashboard/staff-detail-1440.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 900 })
  const positions = await Promise.all([accountDetails, nextStep, activity, danger].map(locator => locator.boundingBox()))
  expect(positions.map(box => box!.y)).toEqual(positions.map(box => box!.y).sort((a, b) => a - b))
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/dashboard/staff-detail-390.png', fullPage: true })

  await root.getByRole('button', { name: 'Generate New Link' }).click()
  await dialog(page).getByRole('button', { name: 'Confirm' }).click()
  await expect(dialog(page).getByRole('heading', { name: 'Enrollment Link Generated' })).toBeVisible()
  await expect(dialog(page).locator('#staff-enrollment')).toHaveValue(/\/staff\/enroll\//)
  await dialog(page).getByRole('button', { name: 'Done' }).click()
  await expect(root.getByRole('button', { name: 'Generate New Link' })).toBeEnabled()

  for (const [label, button, savedStatus] of [
    ['Reject registration', 'Reject Account', 'Rejected'],
    ['Deactivate account', 'Deactivate Account', 'Inactive'],
  ]) {
    const section = root.locator('details').filter({ has: page.getByText(label, { exact: true }) })
    await section.locator('summary').click()
    await section.getByLabel('Reason (required)').fill(`QA ${label}`)
    await section.getByRole('button', { name: button, exact: true }).click()
    await expect(dialog(page).getByRole('heading', { name: button })).toBeVisible()
    await dialog(page).getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect(root.locator('.staff-status')).toHaveText(savedStatus)
  }
  await expect(root.getByRole('heading', { name: 'Danger zone' })).toHaveCount(0)
  await page.reload()
  await ready(page)
  await expect(root.locator('.staff-status')).toHaveText('Inactive')
  await root.getByRole('link', { name: 'All Staff' }).click()
  await expect(page).toHaveURL(/\/admin\/staff\/$/)

  await page.emulateMedia({ colorScheme: 'light' })
  await page.setViewportSize({ width: 320, height: 900 })
  await page.goto('/admin/staff/?q=staff%40example.test')
  await ready(page)
  await viewFirst(page)
  await page.getByRole('link', { name: 'Open Account Page' }).click()
  await ready(page)
  await expect(page.locator('html')).toHaveAttribute('data-lx-theme', 'light')
  await expect(root.locator('.staff-status')).toHaveText('Active')
  await expect(steps.nth(2)).toContainText('Not recorded')
  await expect(steps.nth(3)).toHaveAttribute('data-step-state', 'Completed')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

for (const [width, theme] of [[320, 'dark'], [1440, 'light']] as const) {
  test(`Generate New Link confirmation layout and dismissal at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await page.emulateMedia({ colorScheme: theme })
    await login(page)
    const response = await page.request.get('/admin/staff/new')
    const csrf = await page.evaluate(html => new DOMParser().parseFromString(html, 'text/html')
      .querySelector<HTMLInputElement>('[name=csrf_token]')!.value, await response.text())
    const email = `staff-confirm-${width}@example.test`
    expect((await page.request.post('/admin/staff/new', {
      form: { csrf_token: csrf, full_name: 'Confirmation QA', email },
    })).status()).toBe(200)
    await page.goto(`/admin/staff/?q=${encodeURIComponent(email)}`)
    await ready(page)
    await viewFirst(page)
    const trigger = page.locator('.staff-sheet').getByRole('button', { name: 'Generate New Link' })
    const modal = page.getByRole('dialog', { name: 'Generate New Link' })
    const title = modal.getByRole('heading', { name: 'Generate New Link' })
    const description = modal.getByText('Generate a replacement enrollment link? The previous link will stop working.')
    const cancel = modal.getByRole('button', { name: 'Cancel' })
    const confirm = modal.getByRole('button', { name: 'Confirm' })
    const close = modal.getByRole('button', { name: 'Close' })

    await trigger.click()
    await expect(modal).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('generate-new-link.png'), animations: 'disabled' })
    const [box, heading, copy, cancelBox, confirmBox, closeBox] = await Promise.all(
      [modal, title, description, cancel, confirm, close].map(async locator => (await locator.boundingBox())!),
    )
    expect(box.width).toBe(Math.min(480, width - 32))
    expect(box.x + box.width / 2).toBeCloseTo(width / 2, 0)
    expect(box.y + box.height / 2).toBeCloseTo(450, 0)
    expect(heading.width).toBeGreaterThan(box.width * 0.7)
    expect(heading.height).toBeLessThanOrEqual(24)
    expect(copy.x).toBeCloseTo(heading.x, 0)
    expect(copy.y).toBeGreaterThan(heading.y)
    expect(copy.width).toBeGreaterThan(box.width * 0.7)
    expect(closeBox.x).toBeGreaterThan(heading.x + heading.width)
    expect(cancelBox.y).toBeCloseTo(confirmBox.y, 0)
    expect(cancelBox.x).toBeLessThan(confirmBox.x)
    expect(box.x + box.width - confirmBox.x - confirmBox.width).toBeLessThanOrEqual(24)
    await expect(page.locator('html')).toHaveAttribute('data-lx-theme', theme)
    await expect(modal).toHaveCSS('background-color', theme === 'dark' ? 'rgb(30, 41, 59)' : 'rgb(255, 255, 255)')

    for (const dismiss of [
      () => cancel.click(),
      () => close.click(),
      () => page.keyboard.press('Escape'),
      () => page.mouse.click(1, 1),
    ]) {
      await dismiss()
      await expect(modal).toHaveCount(0)
      await trigger.click()
    }

    let requests = 0
    let release!: () => void
    const pending = new Promise<void>(resolve => { release = resolve })
    await page.route('**/admin/staff/*/enroll-link', async route => {
      if (++requests === 1) {
        await pending
        await route.fulfill({ status: 503, body: 'Unavailable' })
      } else {
        await route.continue()
      }
    })
    await confirm.click()
    try {
      await expect(confirm).toBeDisabled()
      await expect(cancel).toBeDisabled()
      await expect(confirm.locator('svg')).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(modal).toBeVisible()
      expect(requests).toBe(1)
    } finally {
      release()
    }
    await expect(modal.getByRole('alert')).toContainText('not confirmed')
    await expect(confirm).toBeEnabled()
    await confirm.click()
    await expect(dialog(page).getByRole('heading', { name: 'Enrollment Link Generated' })).toBeVisible()
    expect(requests).toBe(2)
  })
}
