import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Layers, LayoutDashboard, List, SlidersHorizontal } from 'lucide-react'
import '@/index.css'
import '@/components/foundation/foundation.css'
import { AppShell, PageContainer, PageHeading, DataTable, FilterBar, SearchField, Pagination, StatusBadge, TextField,
  ContentDialog, ConfirmationDialog, LoadingState, EmptyState, ErrorState, ToastNotifications, type NavigationGroup, type ToastMessage } from '@/components/foundation'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

// Component fixtures only. No orders, payment operations, auth replacement or fake success.
export function FoundationPreview() {
  const role = new URLSearchParams(location.search).get('role') === 'staff' ? 'staff' : 'admin'
  const [query, setQuery] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [messages, setMessages] = useState<ToastMessage[]>([])
  const groups: NavigationGroup[] = [{ label: 'Foundation', items: [
    { label: 'Component overview', href: '#overview', icon: LayoutDashboard, active: true },
    { label: 'Table patterns', href: '#tables', icon: List },
    ...(role === 'admin' ? [{ label: 'Admin presentation', href: '#forms', icon: SlidersHorizontal }] : []),
  ] }]
  return <AppShell role={role} brand={<span className="flex items-center gap-2"><Layers className="text-primary" aria-hidden="true" />Laundrix</span>}
    groups={groups} account={<p>{role === 'admin' ? 'Admin' : 'Staff'} component preview</p>}
    header={<span>Foundation / Shared components</span>}>
    <PageContainer><PageHeading title="Frontend foundation" description="Component fixtures only — no business operations are connected."
      actions={<Button variant="outline" asChild><a href={`?role=${role === 'admin' ? 'staff' : 'admin'}`}>Preview {role === 'admin' ? 'Staff' : 'Admin'}</a></Button>} />
      <Card id="overview"><CardHeader><CardTitle>Shared controls</CardTitle></CardHeader><CardContent className="flex flex-wrap items-center gap-3">
        <ContentDialog title="Dialog preview" description="Keyboard focus stays inside this dialog until it closes." trigger={<Button variant="outline">Open dialog</Button>}><p>Reusable content area.</p></ContentDialog>
        <ConfirmationDialog open={confirm} onOpenChange={setConfirm} title="Confirmation preview" description="This fixture performs no operation. Cancel or close it to return."
          trigger={<Button variant="outline">Open confirmation</Button>} confirmLabel="No operation connected" onConfirm={() => {}} error="Preview only: no submission handler is connected." />
        <Button variant="outline" onClick={() => setMessages([{ id: 'preview', message: 'Component preview notification. No operation was performed.' }])}>Show notification</Button>
        <StatusBadge label="Informational" tone="info" /><StatusBadge label="Attention" tone="warn" /><StatusBadge label="Unavailable" tone="danger" />
      </CardContent></Card>
      <section id="tables" className="grid gap-4"><h2 className="text-lg font-semibold">Table patterns</h2>
        <FilterBar><SearchField label="Search components" value={query} onChange={event => setQuery(event.target.value)} />
          <Button variant="outline" onClick={() => setQuery('')}>Clear</Button></FilterBar>
        <DataTable caption="Available foundation components" columns={[{ key: 'name', header: 'Component', cell: row => row.name }, { key: 'purpose', header: 'Purpose', cell: row => row.purpose }]}
          rows={[{ name: 'Application shell', purpose: 'Responsive navigation and page structure' }, { name: 'Data table', purpose: 'Stable columns and server-owned pagination' }].filter(row => row.name.toLowerCase().includes(query.toLowerCase()))}
          rowKey={row => row.name} />
        <Pagination page={1} pages={1} previousUrl={null} nextUrl={null} />
      </section>
      <Card id="forms"><CardHeader><CardTitle>Form patterns</CardTitle></CardHeader><CardContent className="grid gap-4">
        <TextField label="Example field" hint="Use existing server validation in each module." required />
        <TextField label="Validation example" defaultValue="" error="Example of a field validation message." />
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Feedback patterns</CardTitle></CardHeader><CardContent>
        <LoadingState label="Loading preview" /><EmptyState title="No items" description="An empty state with no invented actions." />
        <ErrorState description="Example error state. Original pages remain available as fallbacks." />
      </CardContent></Card>
      <ToastNotifications messages={messages} onDismiss={id => setMessages(current => current.filter(message => message.id !== id))} />
    </PageContainer>
  </AppShell>
}
createRoot(document.getElementById('foundation-preview')!).render(<>
  <FoundationPreview />
  <div className="lx-react"><ContentDialog title="Legacy portal check" description="Retained React islands use their original portal container."
    trigger={<Button variant="outline">Check legacy portal</Button>}><p>Legacy theme context remains the default.</p></ContentDialog></div>
</>)
