import { z } from 'zod'

const rowSchema=z.object({ kind:z.enum(['services','packages','addons']),id:z.number().int(),name:z.string(),category:z.string(),description:z.string(),code:z.string(),price:z.string(),unit:z.string(),active:z.boolean(),orderable:z.boolean(),icon:z.string(),image:z.string(),visual:z.string(),updated:z.string(),details:z.string(),edit:z.string(),toggle:z.string(),chargeable:z.boolean().optional(),customerSupplied:z.boolean().optional() })
export const catalogSchema=z.object({rows:z.array(rowSchema),tab:z.enum(['all','services','packages','addons']),csrf:z.string(),index:z.string(),create:z.object({services:z.string(),packages:z.string(),addons:z.string()})})
export type CatalogData=z.infer<typeof catalogSchema>
export type CatalogRow=z.infer<typeof rowSchema>
export type Kind=CatalogRow['kind']
export type ViewKind=CatalogData['tab']
export interface Field {name:string;label:string;value:string;checked:boolean;type:string;required:boolean;maxLength:number|undefined;options:{value:string;label:string}[];hint:string;error:string}
export interface CatalogForm {action:string;fields:Field[];errors:string[]}

export function localURL(value:string):string {const url=new URL(value,location.origin);if(url.origin!==location.origin) throw new Error('Invalid catalog destination.');return url.href}
export function parseCatalog(doc:Document):CatalogData {
  const node=doc.getElementById('laundrix-catalog-data')
  if(!node) throw new Error('The catalog response could not be verified. Refresh before retrying.')
  return catalogSchema.parse(JSON.parse(node.textContent || 'null'))
}
async function html(url:string,options?:RequestInit):Promise<{response:Response;doc:Document}> {
  const response=await fetch(localURL(url),{credentials:'same-origin',cache:'no-store',...options})
  const doc=new DOMParser().parseFromString(await response.text(),'text/html')
  if(new URL(response.url).pathname.includes('/auth/') || new URL(response.url).pathname.includes('/staff-auth/')) throw new Error('Please sign in again before continuing.')
  return {response,doc}
}
export async function fetchCatalog(url:string):Promise<CatalogData> {
  const {response,doc}=await html(url,{signal:AbortSignal.timeout(15000)})
  if(!response.ok) throw new Error('Catalog could not be loaded. Please retry.')
  return parseCatalog(doc)
}
function parseForm(doc:Document,action:string):CatalogForm {
  const form=doc.querySelector<HTMLFormElement>('form.form-card')
  if(!form) throw new Error('The original catalog form could not be loaded.')
  const fields=Array.from(form.querySelectorAll<HTMLInputElement|HTMLSelectElement|HTMLTextAreaElement>('input[name],select[name],textarea[name]')).map(input=>{
    const block=input.closest('.field'),label= input.id ? form.querySelector<HTMLLabelElement>(`label[for="${CSS.escape(input.id)}"]`) : input.closest('label')
    return {name:input.name,label:(label?.textContent || input.name).replace(/\*/g,'').trim(),value:input.value,
      checked:input instanceof HTMLInputElement && input.checked,type:input instanceof HTMLSelectElement ? 'select' : input instanceof HTMLTextAreaElement ? 'textarea' : input.type,
      required:input.required,maxLength:'maxLength' in input && input.maxLength>0 ? input.maxLength : undefined,
      options:input instanceof HTMLSelectElement ? Array.from(input.options).map(option=>({value:option.value,label:option.textContent || option.value})) : [],
      hint:block?.querySelector('.hint')?.textContent || '',error:block?.querySelector('.field-error')?.textContent || ''}
  })
  return {action:localURL(action),fields,errors:Array.from(form.querySelectorAll('.field-error')).map(node=>node.textContent || '')}
}
export async function fetchForm(url:string,signal:AbortSignal):Promise<CatalogForm> {
  const {response,doc}=await html(url,{signal})
  if(!response.ok) throw new Error('Catalog form could not be loaded. Please retry.')
  return parseForm(doc,url)
}
export async function saveForm(form:CatalogForm,body:FormData):Promise<{data:CatalogData}|{form:CatalogForm}> {
  const {response,doc}=await html(form.action,{method:'POST',body})
  if(response.status===422) return {form:parseForm(doc,form.action)}
  if(!response.ok || !response.redirected) throw new Error('Saving could not be confirmed. Refresh the catalog before retrying.')
  return {data:parseCatalog(doc)}
}
export async function toggleAvailability(row:CatalogRow,target:boolean,index:string):Promise<CatalogData> {
  // The original endpoint toggles rather than sets a value. Check current saved state
  // first, including after an ambiguous failure, so retry cannot toggle it backwards.
  const fresh=await fetchCatalog(index),saved=fresh.rows.find(item=>item.id===row.id && item.kind===row.kind)
  if(!saved) throw new Error('This catalog record is no longer available.')
  if(saved.active===target) return fresh
  const body=new FormData();body.set('csrf_token',fresh.csrf)
  const {response,doc}=await html(saved.toggle,{method:'POST',body})
  if(!response.ok || !response.redirected) throw new Error('Availability could not be confirmed. Refresh before retrying.')
  const data=parseCatalog(doc),updated=data.rows.find(item=>item.id===row.id && item.kind===row.kind)
  if(updated?.active!==target) throw new Error('Availability changed concurrently. Refresh and check the saved state.')
  return data
}
