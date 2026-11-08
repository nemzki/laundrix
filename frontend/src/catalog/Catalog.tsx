import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from 'react'
import { createPortal } from 'react-dom'
import { Pencil, Plus, Search, LoaderCircle, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Dialog,DialogContent,DialogTitle,DialogDescription,DialogHeader } from '@/components/ui/dialog'
import { Tabs,TabsList,TabsTrigger,TabsContent } from '@/components/ui/tabs'
import { Table,TableHeader,TableHead,TableBody,TableCell,TableRow } from '@/components/ui/table'
import { Switch } from '@/components/ui/switch'
import { fetchCatalog,fetchForm,saveForm,toggleAvailability,type CatalogData,type CatalogForm,type CatalogRow,type Kind,type ViewKind } from './api'
import { Editor } from './Editor'

const titles:Record<Kind,string>={services:'Services',packages:'Packages',addons:'Add-ons'}
const singular:Record<Kind,string>={services:'service',packages:'package',addons:'add-on'}
// These are the ORIGINAL server-rendered, escaped catalog SVG/image assets.
function CatalogIcon({row}:{row:CatalogRow}) {
  return <span className="catalog-icon" dangerouslySetInnerHTML={{__html:row.visual}} />
}
export function Catalog({initial,onReady}:{initial:CatalogData;onReady:()=>void}) {
  const [data,setData]=useState(initial),[kind,setKind]=useState<ViewKind>(initial.tab),[query,setQuery]=useState('')
  const [editor,setEditor]=useState<{kind:Kind;row:CatalogRow|null;url:string}|null>(null),[form,setForm]=useState<CatalogForm|null>(null),[formVersion,setFormVersion]=useState(0)
  const [pending,setPending]=useState(false),[loading,setLoading]=useState(false),[error,setError]=useState(''),[formError,setFormError]=useState(''),[notice,setNotice]=useState('')
  const [confirmation,setConfirmation]=useState<CatalogRow|null>(null)
  const lock=useRef(false),lastTrigger=useRef<HTMLElement|null>(null)
  const rows=kind==='all' ? data.rows : data.rows.filter(row=>row.kind===kind)
  const searchLabel=kind==='all' ? 'catalog' : titles[kind].toLowerCase()
  const shown=rows.filter(row=>`${row.name} ${row.description} ${row.details} ${row.code} ${row.category}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  useLayoutEffect(onReady,[onReady])
  useEffect(()=>{
    if(!editor) return
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);let disposed=false
    fetchForm(editor.url,controller.signal).then(next=>{setForm(next);setFormVersion(value=>value+1)}).catch(reason=>{if(!disposed) setFormError(reason instanceof Error ? reason.message : 'Form could not be loaded.')})
      .finally(()=>clearTimeout(timer))
    return ()=>{disposed=true;controller.abort();clearTimeout(timer)}
  },[editor])
  function begin(row:CatalogRow|null,event?:MouseEvent,createKind?:Kind) {
    if(lock.current) return
    const target=row?.kind || createKind || (kind==='all' ? 'services' : kind)
    if(!target) return
    lastTrigger.current=(event?.currentTarget as HTMLElement) || document.activeElement as HTMLElement
    setNotice('');setForm(null);setFormError('');setEditor({kind:target,row,url:row?.edit || data.create[target]})
  }
  async function refresh() {setLoading(true);setError('');try{setData(await fetchCatalog(data.index))}catch(reason){setError(reason instanceof Error ? reason.message : 'Catalog unavailable.')}finally{setLoading(false)}}
  async function toggle(row:CatalogRow) {
    if(lock.current) return
    lock.current=true;setPending(true);setError('');setConfirmation(null);setNotice('')
    try{const saved=await toggleAvailability(row,!row.active,data.index);setData(saved);setNotice(`${row.name} availability saved.`)}catch(reason){setError(reason instanceof Error ? reason.message : 'Availability was not confirmed.')}
    finally{lock.current=false;setPending(false)}
  }
  async function save(body:FormData) {
    if(!editor || !form || lock.current) return
    lock.current=true;setPending(true);setFormError('')
    try {
      const result=await saveForm(form,body)
      if('form' in result){setForm(result.form);setFormVersion(value=>value+1);return}
      setData(result.data);setNotice(`${titles[editor.kind]} saved successfully.`);setEditor(null)
    } catch(reason){setFormError(reason instanceof Error ? reason.message : 'Saving could not be confirmed.')}
    finally{lock.current=false;setPending(false)}
  }
  function switchKind(value:string) {if(!['all','services','packages','addons'].includes(value))return;setKind(value as ViewKind);const url=new URL(location.href);url.searchParams.set('tab',value);history.replaceState(null,'',url)}
  return <>
    {createPortal(<Button onClick={event=>begin(null,event)} disabled={pending}><Plus size={16} /> Add {kind==='packages' ? 'Package' : kind==='addons' ? 'Add-on' : 'Service'}</Button>,document.getElementById('catalog-action-react')!)}
    {createPortal(<>{rows.filter(row=>row.orderable).length} of {rows.length} {kind==='all' ? 'entries' : titles[kind].toLowerCase()} available for new orders.</>,document.getElementById('catalog-summary-react')!)}
    <Tabs value={kind} onValueChange={switchKind}><Card className="gap-0 overflow-hidden p-0 shadow-none">
      <TabsList aria-label="Catalog modules" className="catalog-module-tabs">{(['all','services','packages','addons'] as ViewKind[]).map(value=><TabsTrigger key={value} value={value}>{value==='all' ? 'All' : titles[value]} <span>{value==='all' ? data.rows.length : data.rows.filter(row=>row.kind===value).length}</span></TabsTrigger>)}</TabsList>
      <TabsContent value={kind} className="m-0">
      <div className="catalog-controls"><div className="catalog-search"><Search aria-hidden="true" className="pointer-events-none h-4 w-4 shrink-0 text-slate-500" /><Input type="search" aria-label="Search catalog" placeholder="Search catalog" value={query} onChange={event=>setQuery(event.target.value)} className="catalog-search-input" /></div>{query && <Button variant="ghost" onClick={()=>{setQuery('')}}>Clear Filters</Button>}</div>
      {error && <div role="alert" className="catalog-error"><AlertCircle size={16} /><span>{error}</span><Button variant="outline" onClick={refresh} disabled={loading}>Retry</Button></div>}
      {loading ? <div role="status" className="p-4"><span className="sr-only">Loading catalog</span>{Array.from({length:6},(_,i)=><div key={i} className="mb-3 h-8 animate-pulse rounded bg-slate-100" />)}</div> : <Table><TableHeader><TableRow><TableHead>{kind==='all' ? 'Entry' : kind==='services' ? 'Service' : kind==='packages' ? 'Package' : 'Add-on'}</TableHead>{kind!=='addons' && <TableHead>{kind==='all' ? 'Module' : 'Category'}</TableHead>}<TableHead className="text-right">Price</TableHead>{kind==='addons' ? <><TableHead>Chargeable</TableHead><TableHead>Customer-supplied</TableHead></> : <TableHead>{kind==='all' ? 'Details' : kind==='services' ? 'Unit':'Range'}</TableHead>}<TableHead>Available</TableHead><TableHead className="text-right">Action</TableHead></TableRow></TableHeader>
        <TableBody>{shown.map(row=><TableRow key={`${row.kind}:${row.id}`} data-catalog-row={`${row.kind}-${row.id}`}><TableCell><div className="flex items-start gap-3"><CatalogIcon row={row} /><div className="min-w-0"><strong className="font-medium">{row.name}</strong><p className="mt-1 text-xs text-muted-foreground">{row.description || row.code}</p>{row.details && <p className="mt-1 text-xs text-muted-foreground">{row.details}</p>}</div></div></TableCell>{kind!=='addons' && <TableCell><Badge variant={kind==='all' ? row.kind : 'secondary'}>{kind==='all' ? titles[row.kind] : row.category}</Badge></TableCell>}<TableCell className="whitespace-nowrap text-right tabular-nums">{row.price}</TableCell>{kind==='addons' ? <><TableCell>{row.chargeable ? 'Yes':'No'}</TableCell><TableCell>{row.customerSupplied ? 'Allowed':'Not allowed'}</TableCell></> : <TableCell className="whitespace-nowrap">{kind==='all' && row.kind==='addons' ? `Chargeable: ${row.chargeable ? 'Yes':'No'} | Customer-supplied: ${row.customerSupplied ? 'Allowed':'Not allowed'}` : row.unit}{kind==='all' && row.category && <p className="mt-1 text-xs text-muted-foreground">{row.category}</p>}{row.kind==='services' && !row.orderable && row.active && <p className="mt-1 text-xs text-amber-800">Configure a pricing unit</p>}</TableCell>}
          <TableCell><div className="flex items-center gap-2"><Switch aria-label={`Available: ${row.name}`} checked={row.active} disabled={pending} onCheckedChange={()=>{if(row.active)setConfirmation(row);else void toggle(row)}} /><span className="text-xs text-muted-foreground">{row.active ? 'Enabled':'Disabled'}</span></div></TableCell><TableCell className="text-right"><Button variant="outline" onClick={event=>begin(row,event)} disabled={pending}><Pencil size={14} /> Edit</Button></TableCell></TableRow>)}{!shown.length && <TableRow><TableCell colSpan={6} className="py-10 text-center text-muted-foreground">{query ? 'No entries match your filters.' : `No ${searchLabel} yet.`}</TableCell></TableRow>}</TableBody></Table>}
      </TabsContent>
    </Card></Tabs>
    {notice && <div role="status" className="catalog-toast"><span>{notice}</span><Button variant="ghost" size="icon-sm" aria-label="Dismiss notification" onClick={()=>setNotice('')}>×</Button></div>}
    <Dialog open={Boolean(editor)} onOpenChange={open=>{if(!open && !pending)setEditor(null)}}><DialogContent className={`catalog-dialog ${editor && !editor.row ? `catalog-dialog-add ${editor.kind==='services' ? 'catalog-dialog-add-service' : ''}` : ''}`} onEscapeKeyDown={event=>{if(pending)event.preventDefault()}} onPointerDownOutside={event=>{if(pending)event.preventDefault()}} onCloseAutoFocus={event=>{event.preventDefault();if(lastTrigger.current?.isConnected)lastTrigger.current.focus()}}>
      <DialogHeader className="catalog-dialog-header"><DialogTitle>{editor?.row ? 'Edit':'Add'} {editor ? singular[editor.kind].replace(/^./,letter=>letter.toUpperCase()) : ''}</DialogTitle><DialogDescription>{editor?.row || editor?.kind==='services' ? 'Price changes apply to new orders only.' : 'Enter the catalog details below. Availability follows the existing New Order rules.'}</DialogDescription></DialogHeader>
      {formError && <div role="alert" className="catalog-error"><span>{formError}</span>{!form && <Button variant="outline" onClick={()=>{setFormError('');setEditor(previous=>previous ? {...previous}:null)}}>Retry</Button>}</div>}
      {editor && form ? <Editor key={formVersion} form={form} row={editor.row} kind={editor.kind} categories={[...new Set(data.rows.filter(row=>row.kind===editor.kind).map(row=>row.category).filter(Boolean))]} busy={pending} onSubmit={save} onCancel={()=>setEditor(null)} /> : !formError && <div className="flex items-center gap-2 p-6" role="status"><LoaderCircle className="size-4 animate-spin" />Loading original catalog form…</div>}
    </DialogContent></Dialog>
    <Dialog open={Boolean(confirmation)} onOpenChange={open=>{if(!open)setConfirmation(null)}}><DialogContent><DialogHeader><DialogTitle>Disable {confirmation?.name}?</DialogTitle><DialogDescription>Staff will no longer be able to select this entry for new orders. Existing orders are not affected.</DialogDescription></DialogHeader><div className="flex justify-end gap-2"><Button variant="outline" onClick={()=>setConfirmation(null)}>Cancel</Button><Button onClick={()=>{if(confirmation)void toggle(confirmation)}}>Disable entry</Button></div></DialogContent></Dialog>
  </>
}
