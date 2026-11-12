import { useState, type FormEvent } from 'react'
import { LoaderCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import type { CatalogForm, CatalogRow, Field, Kind } from './api'

export function Editor({ form, row, kind, categories, busy, onSubmit, onCancel }: {
  form:CatalogForm;row:CatalogRow|null;kind:Kind;categories:string[];busy:boolean;onSubmit:(body:FormData)=>void;onCancel:()=>void
}) {
  const serviceCreate=kind==='services' && !row
  const [values,setValues]=useState(()=>form.fields.map(field=>{
    // Defaults affect only a fresh Add Service form; validation responses retain entered values.
    if(serviceCreate && !form.errors.length){
      if(field.name==='pricing_unit' && !field.value && field.options.some(option=>option.value==='load')) return 'load'
    }
    return field.type==='checkbox' ? field.checked : field.value
  }))
  const [customCategory,setCustomCategory]=useState(false)
  const set=(index:number,value:string|boolean)=>setValues(previous=>previous.map((old,i)=>i===index ? value : old))
  const get=(name:string)=>String(values[form.fields.findIndex(field=>field.name===name)] ?? '')
  const unitField=form.fields.find(field=>field.name==='pricing_unit')
  const unitLabel=unitField?.options.find(option=>option.value===get('pricing_unit'))?.label
  const appearance=['icon_key','image_url']
  function submit(event:FormEvent<HTMLFormElement>) {event.preventDefault();if(!busy && event.currentTarget.reportValidity()) onSubmit(new FormData(event.currentTarget))}
  function fieldNode(field:Field,index:number) {
    const id=`catalog-${field.name}-${index}`,value=values[index]
    if(field.type==='hidden') return <input key={id} type="hidden" name={field.name} value={String(value)} />
    let control
    if(field.type==='checkbox') {
      const active=field.name==='is_active'
      control=active ? <div className="flex items-center justify-between gap-4"><div><Label htmlFor={id}>Available for New Orders</Label><p className="mt-1 text-xs text-muted-foreground">Disabled entries are hidden from New Order.</p></div><Switch id={id} checked={Boolean(value)} onCheckedChange={checked=>set(index,checked)} disabled={busy} /><input type="hidden" name={field.name} value="on" disabled={!value} /></div> :
        <label className="flex items-start gap-2 text-sm" htmlFor={id}><input id={id} type="checkbox" name={field.name} value={field.value} checked={Boolean(value)} onChange={event=>set(index,event.target.checked)} disabled={busy} className="mt-0.5 size-4 accent-blue-600" />{field.label}</label>
    } else if(field.name==='category' && kind==='services') {
      control=<><Label htmlFor={id}>{field.label}</Label><Input id={id} name={field.name} value={String(value)} onChange={event=>set(index,event.target.value)} required={field.required} maxLength={field.maxLength} disabled={busy} aria-invalid={Boolean(field.error)} placeholder="Category name" /></>
    } else if(field.name==='category') {
      const options=[...new Set([...categories,field.value].filter(Boolean))]
      const selected=options.indexOf(String(value))
      control=<><Label htmlFor={id}>{field.label}</Label><Select value={customCategory || selected<0 ? 'custom' : `category-${selected}`} onValueChange={option=>{if(option==='custom') setCustomCategory(true);else{setCustomCategory(false);set(index,options[Number(option.replace('category-',''))])}}} disabled={busy}>
        <SelectTrigger id={id} className="w-full"><SelectValue /></SelectTrigger><SelectContent position="popper">{options.map((option,i)=><SelectItem key={option} value={`category-${i}`}>{option}</SelectItem>)}<SelectItem value="custom">Enter another category…</SelectItem></SelectContent>
      </Select>{customCategory || selected<0 ? <Input className="mt-2" aria-label="Custom category" name={field.name} value={String(value)} onChange={event=>set(index,event.target.value)} required={field.required} maxLength={field.maxLength} disabled={busy} placeholder="Category name" /> : <input type="hidden" name={field.name} value={String(value)} />}</>
    } else if(field.type==='select') {
      control=<><Label htmlFor={id}>{field.label}</Label><Select value={String(value) || 'empty-option'} onValueChange={option=>set(index,option==='empty-option' ? '' : option)} disabled={busy}>
        <SelectTrigger id={id} aria-invalid={Boolean(field.error)} className="w-full"><SelectValue /></SelectTrigger><SelectContent position="popper">{field.options.map(option=><SelectItem key={option.value} value={option.value || 'empty-option'}>{option.label}</SelectItem>)}</SelectContent>
      </Select><input type="hidden" name={field.name} value={String(value)} /></>
    } else {
      const price=field.name==='price',range=['min_value','max_value'].includes(field.name),pieces=get('measure_type')==='pieces'
      control=<><Label htmlFor={id}>{serviceCreate && field.name==='name' ? 'Service Name' : serviceCreate && price ? 'Price' : field.label}{field.name==='description' && !field.required ? ' (Optional)' : ''}</Label>
        {field.name==='description' ? <textarea id={id} name={field.name} value={String(value)} onChange={event=>set(index,event.target.value)} required={field.required} maxLength={field.maxLength} disabled={busy} rows={3} placeholder={serviceCreate ? "Short note shown to staff when creating orders" : undefined} className="catalog-textarea" aria-invalid={Boolean(field.error)} /> :
          <div className={price ? 'catalog-price' : undefined}>{price && <span className="catalog-peso" aria-hidden="true">₱</span>}<Input id={id} name={field.name} value={String(value)} onChange={event=>set(index,event.target.value)} required={field.required} maxLength={field.maxLength} disabled={busy} placeholder={serviceCreate ? price ? "0.00" : field.name==='name' ? "e.g. Wash, Dry & Fold" : undefined : undefined}
            type={price || range ? 'number' : 'text'} inputMode={price || range ? 'decimal' : undefined} min={price ? 0 : range ? pieces ? 1 : 0.01 : undefined} max={price ? 99999.99 : range ? 9999 : undefined} step={price ? '0.01' : range ? pieces ? '1' : '0.01' : undefined}
            aria-invalid={Boolean(field.error)} className={price ? `pl-7 ${kind==='services' && get('pricing_unit') ? 'pr-32' : ''}` : undefined} />{price && kind==='services' && get('pricing_unit') && <span className="catalog-unit-suffix">{serviceCreate ? `/ ${get('pricing_unit')}` : unitLabel}</span>}</div>}</>
    }
    return <div className="catalog-field" key={id}>{control}{field.hint && <p className="text-xs text-muted-foreground">{field.hint}</p>}{field.error && <p className="text-xs text-red-700" role="alert">{field.error}</p>}</div>
  }
  const byName=(name:string)=>{const index=form.fields.findIndex(field=>field.name===name);return index<0 ? null : fieldNode(form.fields[index],index)}
  return <form onSubmit={submit} className="catalog-editor-form">
    <div className="catalog-editor-body">
      {form.errors.length>0 && <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{[...new Set(form.errors)].join(' ')}</div>}
      {serviceCreate ? <>
        {byName('name')}
        <div className="catalog-service-options">{byName('category')}{byName('pricing_unit')}</div>
        {byName('price')}{byName('description')}{byName('is_active')}
        {/* Original creation requires a permanent code; never silently generate or omit it. */}
        {byName('code')}
        {form.fields.map((field,index)=>['name','category','pricing_unit','price','description','is_active','code',...appearance].includes(field.name) ? null : fieldNode(field,index))}
      </> : form.fields.map((field,index)=>appearance.includes(field.name) ? null : fieldNode(field,index))}
      <details className="catalog-appearance" open={form.fields.some(field=>appearance.includes(field.name) && field.error) || undefined}><summary>Appearance and Catalog Details</summary>
        {row?.code && <div className="catalog-field"><Label htmlFor="catalog-fixed-code">Code (Permanent)</Label><Input id="catalog-fixed-code" readOnly value={row.code} /></div>}
        {row && <p className="mb-3 text-xs text-muted-foreground">Last updated {row.updated}</p>}
        {form.fields.map((field,index)=>appearance.includes(field.name) ? fieldNode(field,index) : null)}
      </details>
      {kind==='packages' && <p className="text-xs text-muted-foreground">Selected included service codes retain the original package rules; they are not charged again.</p>}
      {kind==='services' && !get('pricing_unit') && <p className="rounded-lg bg-amber-50 p-3 text-xs text-amber-900">A pricing unit must be configured before this service can be ordered.</p>}
    </div>
    <div className="catalog-editor-footer"><Button type="button" variant="outline" onClick={onCancel} disabled={busy}>Cancel</Button><Button type="submit" disabled={busy}>{busy && <LoaderCircle className="size-4 animate-spin" />}{busy ? 'Saving…' : row ? 'Save Changes' : kind==='services' ? 'Add Service' : kind==='packages' ? 'Add Package' : 'Add Add-on'}</Button></div>
  </form>
}
