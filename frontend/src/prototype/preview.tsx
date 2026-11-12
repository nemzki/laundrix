import { useState } from 'react'
import { LayoutDashboard, ListFilter, SlidersHorizontal } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@prototype/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@prototype/components/ui/card'
import { Toaster } from '@prototype/components/ui/sonner'
import { TooltipProvider } from '@prototype/components/ui/tooltip'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@prototype/components/ui/empty'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@prototype/components/ui/select'
import { AppShell, AppHeader, PageContainer, PageHeader, DataTable, FilterBar, SearchField, TextField, StatusBadge, LoadingState, ErrorState,
  TablePagination, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger,
  AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
  type NavigationSection } from '@prototype/components/laundrix'

const sections: NavigationSection[] = [{ label: 'Foundation', items: [
  { label: 'Components', href: '#components', icon: LayoutDashboard, roles: ['admin', 'staff'], active: true },
  { label: 'Table patterns', href: '#table', icon: ListFilter, roles: ['admin', 'staff'] },
  { label: 'Admin presentation', href: '#fields', icon: SlidersHorizontal, roles: ['admin'] },
] }]
const fixtures = [{ name: 'Page layout', purpose: 'Reusable structure' }, { name: 'Table', purpose: 'Server-owned data rendering' }]

export function FoundationPreview() {
  const role = new URLSearchParams(location.search).get('role') === 'staff' ? 'staff' : 'admin'
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<string | null>('all')
  const items = fixtures.filter(item => item.name.toLowerCase().includes(query.toLowerCase()) && (filter === 'all' || item.name === 'Table'))
  return <TooltipProvider><AppShell role={role} sections={sections} account={<p className="px-2 py-1 text-xs text-muted-foreground">{role === 'admin' ? 'Admin' : 'Staff'} layout preview · no session</p>}
    header={<AppHeader section="Foundation" title="Shared components" />}>
    <PageContainer><PageHeader title="Frontend foundation" description="Component preview only. No business operations or database connection."
      actions={<Button variant="outline" nativeButton={false} render={<a href={`?role=${role === 'admin' ? 'staff' : 'admin'}`} />}>Preview {role === 'admin' ? 'Staff' : 'Admin'}</Button>} />
      <Card id="components" size="sm"><CardHeader><CardTitle>Shared controls</CardTitle></CardHeader><CardContent className="flex flex-wrap items-center gap-2">
        <Dialog><DialogTrigger render={<Button variant="outline" />}>Open dialog</DialogTrigger><DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto"><DialogHeader><DialogTitle>Dialog preview</DialogTitle><DialogDescription>Focus remains inside until you close this preview.</DialogDescription></DialogHeader><p>Reusable dialog content.</p></DialogContent></Dialog>
        <AlertDialog><AlertDialogTrigger render={<Button variant="outline" />}>Open confirmation</AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Confirmation preview</AlertDialogTitle><AlertDialogDescription>No operation is connected. Business modules must provide a real handler.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><Button disabled>No operation connected</Button></AlertDialogFooter></AlertDialogContent></AlertDialog>
        <Button variant="outline" onClick={() => toast.info('Component preview notification. No operation was performed.')}>Show notification</Button>
        <StatusBadge label="Example label" />
      </CardContent></Card>
      <section id="table" className="flex min-w-0 flex-col gap-4"><h2 className="text-lg font-semibold">Table patterns</h2><FilterBar>
        <SearchField value={query} onChange={setQuery} label="Search components" placeholder="Search components" className="min-w-0 flex-1 sm:w-auto" />
        <Select items={[{ value: 'all', label: 'All components' }, { value: 'table', label: 'Tables only' }]} value={filter} onValueChange={setFilter}>
          <SelectTrigger aria-label="Component type"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All components</SelectItem><SelectItem value="table">Tables only</SelectItem></SelectContent>
        </Select><Button variant="outline" onClick={() => { setQuery(''); setFilter('all') }}>Clear</Button>
      </FilterBar><DataTable caption="Foundation component examples" columns={[{ key: 'name', label: 'Component', render: item => item.name }, { key: 'purpose', label: 'Purpose', render: item => item.purpose }]} items={items} rowKey={item => item.name} />
        <TablePagination page={1} pageCount={1} total={items.length} pageSize={10} onPageChange={() => {}} noun="components" />
      </section>
      <Card id="fields" size="sm"><CardHeader><CardTitle>Form patterns</CardTitle></CardHeader><CardContent className="flex flex-col gap-4">
        <TextField label="Example field" description="Reuse original server validations when integrating a module." />
        <TextField label="Validation example" error="Example field error, for presentation only." />
      </CardContent></Card>
      <Card size="sm"><CardHeader><CardTitle>Feedback states</CardTitle></CardHeader><CardContent className="flex flex-col gap-4">
        <LoadingState label="Loading state preview" /><ErrorState title="Example error" description="Show the real server error when an operation fails." />
        <Empty><EmptyHeader><EmptyTitle>No items</EmptyTitle><EmptyDescription>Reusable empty state.</EmptyDescription></EmptyHeader></Empty>
      </CardContent></Card>
    </PageContainer>
  </AppShell><Toaster theme="light" position="top-right" richColors closeButton /></TooltipProvider>
}
