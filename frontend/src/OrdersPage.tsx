import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from 'react'
import { useForm } from 'react-hook-form'
import { ArrowRight, ChevronLeft, ChevronRight, ClipboardList, LoaderCircle, Printer, Search } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Form, FormControl, FormField, FormItem, FormLabel } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { OrdersPageData, OrderSummary } from './orders-data'
import './orders.css'
import { useOrdersNavigation } from './use-orders-navigation'

function StatusBadge({ label, tone }: { label: string; tone: string }) {
  return <Badge variant="outline" className="lx-status h-auto min-h-5 max-w-full whitespace-normal text-left" data-tone={tone}>{label}</Badge>
}
function OrderStatuses({ order }: { order: OrderSummary }) {
  return <div className="mo-mobile-statuses">
    <div><span className="sr-only">Laundry: </span>
      <StatusBadge label={order.laundry} tone={order.laundryTone} />
      {order.awaiting && <span className="mt-1 block text-xs text-muted-foreground">Awaiting receipt</span>}
    </div>
    <div><span className="sr-only">Payment: </span>
      <StatusBadge label={order.payment} tone={order.paymentTone} />
      {order.balanceNote && <span className="mt-1 block text-xs text-muted-foreground">Balance {order.balanceNote}</span>}
    </div>
  </div>
}
function OrderDate({ order }: { order: OrderSummary }) {
  const time = order.created.startsWith(order.createdShort) ? order.created.slice(order.createdShort.length).trim() : ''
  return <span className="mo-date" title={order.created}>{order.createdShort}
    {time && <span className="mo-secondary">{time}</span>}
  </span>
}
function SummaryDialog({ order, onClose, restoreFocus }: { order: OrderSummary | null; onClose: () => void; restoreFocus: () => void }) {
  return <Dialog open={order !== null} onOpenChange={open => { if (!open) onClose() }}>
    <DialogContent className="max-h-[85dvh] grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden sm:max-w-lg" onCloseAutoFocus={event => { event.preventDefault(); restoreFocus() }}>
      <DialogHeader><DialogTitle>Order Summary</DialogTitle>
        <DialogDescription>Review this order, print its stub, or open the full order to manage it.</DialogDescription>
      </DialogHeader>
      {order && <>
        <dl className="grid min-h-0 min-w-0 gap-4 overflow-y-auto overscroll-contain pr-1 sm:grid-cols-2" data-order-summary-reference={order.reference}>
          {[
            ['Order reference', order.reference], ['Customer', order.customer],
            ['Contact', order.contact], ['Date Created', order.created],
            ['Total Amount', order.total], ['Amount Paid', order.paid], ['Remaining Balance', order.balance],
          ].map(([label, value]) => <div key={label} className="min-w-0 border-b pb-3">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className={`mt-1 break-words font-medium${label === 'Order reference' ? ' font-mono' : ''}`}>{value || '—'}</dd>
          </div>)}
          <div><dt className="mb-1 text-xs text-muted-foreground">Laundry Status</dt>
            <dd><StatusBadge label={order.laundry} tone={order.laundryTone} />
              {order.awaiting && <span className="mt-1 block text-xs text-muted-foreground">Awaiting receipt</span>}
            </dd>
          </div>
          <div><dt className="mb-1 text-xs text-muted-foreground">Payment Status</dt>
            <dd><StatusBadge label={order.payment} tone={order.paymentTone} /></dd>
          </div>
        </dl>
        <DialogFooter className="mt-2 gap-2 sm:justify-end">
          <Button variant="outline" asChild><a href={order.stubUrl} target="_blank" rel="noopener"><Printer aria-hidden="true" />Print Stub</a></Button>
          <Button asChild><a href={order.detailUrl}><ArrowRight aria-hidden="true" />Open Full Order</a></Button>
        </DialogFooter>
      </>}
    </DialogContent>
  </Dialog>
}
export function OrdersPage({ data: initial, onReady }: { data: OrdersPageData; onReady: () => void }) {
  const { data, pending, error, navigate, filterOrders, retry } = useOrdersNavigation(initial)
  const [selected, setSelected] = useState<{ order: OrderSummary; data: OrdersPageData } | null>(null)
  const trigger = useRef<HTMLButtonElement | null>(null)
  const form = useForm({ defaultValues: { q: data.term } })
  const filtered = Boolean(data.term || data.status)
  useLayoutEffect(onReady, [onReady])
  useEffect(() => {
    form.reset({ q: data.term })
  }, [data, form])
  const follow = (event: MouseEvent<HTMLAnchorElement>, url: string) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    void navigate(url)
  }
  const viewButton = (order: OrderSummary) => <Button variant="outline" size="sm" onClick={event => { trigger.current = event.currentTarget; setSelected({ order, data }) }}
    aria-label={`View order ${order.reference}`} aria-haspopup="dialog">View</Button>
  return <section aria-label="Manage orders" className="manage-orders">
    <Tabs value={data.status || '__all'} activationMode="manual" onValueChange={value => {
      const filter = data.filters.find(f => (f.value || '__all') === value)
      if (filter) filterOrders(filter.url)
    }}>
      <TabsList aria-label="Order status" className="mo-status-tabs">
        {data.filters.map(filter => <TabsTrigger key={filter.value} value={filter.value || '__all'}
          className="mo-status-tab border data-[state=active]:border-primary data-[state=active]:bg-accent data-[state=active]:text-primary">
          <span className="mo-tab-label">{filter.label}</span><span className="mo-tab-count rounded-md bg-muted tabular-nums">{filter.count}</span>
        </TabsTrigger>)}
      </TabsList>
    </Tabs>
      <Form {...form}>
        <form method="get" action={data.indexUrl} role="search" className="mo-filters"
          aria-busy={pending} onSubmit={event => {
            event.preventDefault()
            if (pending) return
            const url = new URL(data.indexUrl, window.location.href)
            const params = new URLSearchParams()
            new FormData(event.currentTarget).forEach((value, key) => { if (typeof value === 'string') params.append(key, value) })
            url.search = params.toString()
            void navigate(url.href)
          }}>
          <FormField control={form.control} name="q" render={({ field }) => <FormItem className="mo-search-field">
            <FormLabel>Search orders</FormLabel><FormControl><Input {...field} className="mo-search-input" type="search" placeholder="Reference, name or contact" autoComplete="off" /></FormControl>
          </FormItem>} />
          <input type="hidden" name="status" value={data.status} />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={pending}>{pending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Search aria-hidden="true" />}Search</Button>
            <Button variant="outline" asChild><a href={data.indexUrl} onClick={event => { form.reset({ q: '' }); follow(event, data.indexUrl) }}>Clear</a></Button>
          </div>
        </form>
      </Form>
    {error && <div role="alert" className="mo-filter-error"><p>{error}</p><Button variant="outline" onClick={retry}>Try again</Button></div>}
    <Card className="mo-table-panel shadow-none">
      <CardHeader className="mo-table-heading">
        <div className="mo-table-title"><CardTitle><h2>Orders</h2></CardTitle><CardDescription>{data.total} {filtered ? 'matching ' : ''}{data.total === 1 ? 'order' : 'orders'}</CardDescription></div>
        {filtered && <Badge variant="secondary">Filtered results</Badge>}
      </CardHeader>
      <CardContent className="mo-table-content">
        {data.orders.length ? <>
          <div className="mo-desktop-table"><div className="mo-table-overflow"><Table className="mo-data-table" scrollable={false}>
            <caption className="sr-only">Order reference, customer, contact, date, laundry status, payment status and order actions.</caption>
            <colgroup><col className="mo-col-order" /><col /><col className="mo-col-contact" /><col className="mo-col-date" /><col className="mo-col-laundry" /><col className="mo-col-payment" /><col className="mo-col-action" /></colgroup>
            <TableHeader><TableRow>
              <TableHead scope="col">Order Reference</TableHead><TableHead scope="col">Customer</TableHead><TableHead scope="col">Contact Number</TableHead>
              <TableHead scope="col">Date Created</TableHead>
              <TableHead scope="col">Laundry Status</TableHead><TableHead scope="col">Payment Status</TableHead><TableHead scope="col" className="mo-action">Action</TableHead>
            </TableRow></TableHeader>
            <TableBody>{data.orders.map(order => <TableRow key={order.reference}>
              <TableCell><strong className="mo-reference">{order.reference}</strong></TableCell>
              <TableCell><span className="mo-customer">{order.customer}</span></TableCell>
              <TableCell><span className="mo-contact">{order.contact}</span></TableCell>
              <TableCell><OrderDate order={order} /></TableCell>
              <TableCell><StatusBadge label={order.laundry} tone={order.laundryTone} />
                {order.awaiting && <span className="mo-secondary">Awaiting receipt</span>}
              </TableCell>
              <TableCell><StatusBadge label={order.payment} tone={order.paymentTone} />
                {order.balanceNote && <span className="mo-secondary mo-money">Balance {order.balanceNote}</span>}
              </TableCell>
              <TableCell className="mo-action">{viewButton(order)}</TableCell>
            </TableRow>)}</TableBody>
          </Table></div></div>
          <div className="mo-mobile-orders divide-y">{data.orders.map(order => <article key={order.reference} className="mo-mobile-order">
            <div className="flex items-start justify-between gap-3"><div className="min-w-0">
              <h3 className="mo-reference">{order.reference}</h3>
              <p className="mo-customer">{order.customer}</p><p className="mo-contact">{order.contact}</p>
            </div>{viewButton(order)}</div>
            <OrderDate order={order} />
            <OrderStatuses order={order} />
          </article>)}</div>
        </> : <div className="mo-empty">
          {!filtered && <ClipboardList className="size-6 text-muted-foreground" aria-hidden="true" />}
          <h3 className="font-semibold">{filtered ? 'No matching orders' : 'No orders yet'}</h3>
          <p className="text-sm text-muted-foreground">{filtered ? 'Try a different reference, customer or status.' : 'Create your first order to get started.'}</p>
          {!filtered && <Button variant="outline" asChild><a href={data.newOrderUrl}>New Order</a></Button>}
        </div>}
      </CardContent>
    </Card>
    {data.pages > 1 && <nav aria-label="Pagination" className="flex flex-wrap items-center justify-between gap-3">
      {data.previousUrl ? <Button variant="outline" asChild><a href={data.previousUrl} onClick={event => follow(event, data.previousUrl!)}><ChevronLeft aria-hidden="true" />Previous</a></Button> : <Button variant="outline" disabled><ChevronLeft aria-hidden="true" />Previous</Button>}
      <span className="text-sm text-muted-foreground" aria-current="page">Page {data.page} of {data.pages}</span>
      {data.nextUrl ? <Button variant="outline" asChild><a href={data.nextUrl} onClick={event => follow(event, data.nextUrl!)}>Next<ChevronRight aria-hidden="true" /></a></Button> : <Button variant="outline" disabled>Next<ChevronRight aria-hidden="true" /></Button>}
    </nav>}
    <SummaryDialog order={selected?.data === data ? selected.order : null} onClose={() => setSelected(null)} restoreFocus={() => trigger.current?.focus()} />
  </section>
}
