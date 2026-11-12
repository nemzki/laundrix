import { z } from 'zod'
import { localURL } from '@/catalog/api'
const row=z.object({id:z.number(),name:z.string(),email:z.string(),role:z.string(),status:z.string(),label:z.string(),identity:z.string(),identityTone:z.string(),created:z.string(),lastLogin:z.string(),detail:z.string()})
const schema=z.object({rows:z.array(row),filters:z.array(z.object({value:z.string(),label:z.string(),count:z.number()})),total:z.number(),page:z.number(),pages:z.number(),perPage:z.number(),status:z.string(),term:z.string(),sort:z.string(),index:z.string(),create:z.string(),counts:z.record(z.string(),z.number())})
const detailSchema=z.object({id:z.number(),name:z.string(),email:z.string(),status:z.string(),label:z.string(),identity:z.string(),identityDecision:z.string(),created:z.string(),lastLogin:z.string(),approved:z.string(),approver:z.string(),changed:z.string(),changedBy:z.string(),reason:z.string(),enrollment:z.string(),activity:z.array(z.object({label:z.string(),time:z.string(),actor:z.string(),detail:z.string(),success:z.boolean()}))})
export type StaffRow=z.infer<typeof row>
export type StaffList=z.infer<typeof schema>
export interface Action {url:string;label:string;description:string;csrf:string;reason:boolean;min:number;max:number}
export type Details=z.infer<typeof detailSchema>&{actions:Action[]}
export interface Enrollment {url:string;staffName:string;expires:string;detail:string;instructions:string[]}
function json(doc:Document,id:string){const node=doc.getElementById(id);if(!node)throw new Error('The server response could not be verified. Reload before retrying.');return JSON.parse(node.textContent || 'null')}
export function parseList(doc:Document){return schema.parse(json(doc,'laundrix-staff-data'))}
async function html(url:string,options:RequestInit={}) {
  const response=await fetch(localURL(url),{credentials:'same-origin',cache:'no-store',...options})
  const doc=new DOMParser().parseFromString(await response.text(),'text/html')
  if(response.status===403 || response.status===401 || new URL(response.url).pathname.includes('/auth/')) throw new Error('You are not authorized. Sign in with an active administrator account.')
  return {response,doc}
}
export async function fetchList(url:string,signal?:AbortSignal){const {response,doc}=await html(url,{signal:signal || AbortSignal.timeout(15000)});if(!response.ok)throw new Error('Staff could not be loaded. Please retry.');return parseList(doc)}
function actions(doc:Document):Action[]{return Array.from(doc.querySelectorAll<HTMLFormElement>('form[data-confirm]')).map(form=>{const reason=form.querySelector<HTMLInputElement>('[name=reason]');return {url:localURL(form.getAttribute('action')!),label:form.querySelector('button[type=submit]')?.textContent?.trim() || 'Confirm',description:form.dataset.confirm || '',csrf:form.querySelector<HTMLInputElement>('[name=csrf_token]')!.value,reason:Boolean(reason),min:reason?.minLength || 3,max:reason?.maxLength || 255}})}
function parseDetail(doc:Document):Details{return {...detailSchema.parse(json(doc,'laundrix-staff-detail')),actions:actions(doc)}}
export async function fetchDetail(url:string,signal?:AbortSignal){const {response,doc}=await html(url,{signal:signal || AbortSignal.timeout(15000)});if(!response.ok)throw new Error('Account details could not be loaded.');return parseDetail(doc)}
export async function fetchCreate(url:string){const {response,doc}=await html(url,{signal:AbortSignal.timeout(15000)});if(!response.ok)throw new Error('Staff form could not be loaded.');const csrf=doc.querySelector<HTMLInputElement>('form [name=csrf_token]')?.value;if(!csrf)throw new Error('The original staff form is unavailable.');return csrf}
function enrollment(doc:Document):Enrollment|null {const field=doc.querySelector<HTMLInputElement>('#enroll-url');if(!field)return null;const card=field.closest<HTMLElement>('.card');const expires=card?.querySelector<HTMLElement>('[data-enrollment-expires]')?.textContent?.trim();const detail=doc.querySelector<HTMLAnchorElement>('.page-actions a')?.getAttribute('href');if(!card||!card.dataset.enrollmentName||!expires||!detail)return null;return {url:field.value,staffName:card.dataset.enrollmentName,expires,detail:localURL(detail),instructions:Array.from(card.querySelectorAll('ol li')).map(li=>li.textContent?.trim() || '')}}
function serverError(doc:Document){return Array.from(doc.querySelectorAll('.flash-error,.alert-error')).map(node=>node.textContent?.trim()).filter(Boolean).join(' ')}
export async function createStaff(url:string,body:FormData):Promise<Enrollment>{
  // This original endpoint commits and returns the one-time link directly, without a redirect.
  const {response,doc}=await html(url,{method:'POST',body});const error=serverError(doc)
  if(error)throw new Error(error)
  if(!response.ok)throw new Error('Creation was not confirmed. Check the staff list before retrying.')
  const link=enrollment(doc);if(!link)throw new Error('Creation could not be verified. Check the staff list before retrying.');return link
}
export async function submitAction(action:Action,reason:string):Promise<{details:Details}|{link:Enrollment}>{
  const body=new FormData();body.set('csrf_token',action.csrf);if(action.reason)body.set('reason',reason)
  const {response,doc}=await html(action.url,{method:'POST',body});const error=serverError(doc)
  if(error)throw new Error(error)
  if(!response.ok)throw new Error('The account action was not confirmed. Reload and check the saved state.')
  const link=enrollment(doc);if(link)return {link}
  if(!response.redirected)throw new Error('The saved account response was not confirmed.')
  return {details:parseDetail(doc)}
}
