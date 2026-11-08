import { expect,test } from '@playwright/test'
for(const role of ['admin','staff'] as const)for(const width of [320,768,1440])test(`internal UI audit ${role} ${width}px`,async({page})=>{
 test.setTimeout(120000)
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message))
 await page.setViewportSize({width,height:1000});await page.goto('/auth/login')
 await expect(page.locator('link[href*="internal-polish"]')).toHaveCount(0)
 if(role==='staff')await page.getByRole('tab',{name:'Staff',exact:true}).click()
 await page.locator(`#${role}-identifier`).fill(role==='admin'?'browseradmin':'staff@example.test');await page.locator(`#${role}-password`).fill('Browser-Test-Password!42');await page.locator(`form[data-auth-form=${role}] button[type=submit]`).click();await expect(page).toHaveURL(/dashboard/)
 const routes=role==='admin'?['/dashboard/','/orders/new','/orders/','/orders/customers','/admin/services/','/admin/staff/','/payments/outstanding','/payments/','/payments/summary','/payments/settings']:['/dashboard/','/orders/new','/orders/','/payments/outstanding']
 for(const route of routes){
  const response=await page.goto(route);expect(response?.status(),route).toBe(200)
  await expect(page.locator('h1').filter({visible:true}).first(),route).toBeVisible()
  for(const selector of ['#laundrix-dashboard','#laundrix-catalog','#laundrix-staff'])if(await page.locator(selector).count())await expect(page.locator(selector)).toHaveAttribute('data-ready','true')
  for(const selector of ['[data-manage-orders]','[data-customer-directory]','[data-outstanding]'])if(await page.locator(selector).count())await expect(page.locator(selector)).toHaveAttribute('data-state','ready')
  await page.evaluate(()=>document.fonts.ready)
  const button=page.locator('main :is(.btn,[data-slot=button]):not(:disabled):not([aria-disabled=true])').filter({visible:true}).first()
  if(await button.count()){
    const before=(await button.boundingBox())!;await button.hover();await button.focus()
    const after=(await button.boundingBox())!;expect(after.width).toBeCloseTo(before.width,1);expect(after.height).toBeCloseTo(before.height,1)
    await expect(button).toBeFocused()
  }

  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),{message:`Horizontal overflow: ${role} ${route} ${width}`}).toBe(true)
  if(route==='/orders/'&&role==='admin'){
   const href=await page.locator('.mo-rows a[data-order-summary]').first().getAttribute('href')
   if(href){const detail=await page.goto(href);expect(detail?.status()).toBe(200);await expect(page.locator('.order-tracker__step')).toHaveCount(6);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)}
  }
  if(route==='/payments/settings'||route==='/payments/summary')await page.screenshot({path:`test-results/dashboard/polish-${width}-${route.split('/').filter(Boolean).pop()}.png`,fullPage:true})
 }
 if(role==='staff'){expect((await page.request.get('/admin/staff/')).status()).toBe(403);expect((await page.request.get('/payments/settings')).status()).toBe(403)}
 expect(errors).toEqual([])
})
