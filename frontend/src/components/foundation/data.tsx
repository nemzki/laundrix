import { useId, type ReactNode, type Key, type ComponentProps } from 'react'
import { Search, ChevronLeft, ChevronRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { EmptyState } from './feedback'

export interface DataColumn<T> { key: string; header: string; cell: (row: T) => ReactNode }
/** Rendering only: all filtering, sorting, totals and pagination stay with the caller/server. */
export function DataTable<T>({ caption, columns, rows, rowKey, empty, busy = false }: {
  caption: string; columns: DataColumn<T>[]; rows: T[]; rowKey: (row: T) => Key; empty?: ReactNode; busy?: boolean
}) {
  return <div className="fx-table-panel" aria-busy={busy}>
    <Table className="fx-table"><caption className="sr-only">{caption}</caption>
      <TableHeader><TableRow>{columns.map(c => <TableHead key={c.key} scope="col">{c.header}</TableHead>)}</TableRow></TableHeader>
      <TableBody>{rows.length ? rows.map(row => <TableRow key={rowKey(row)}>{columns.map(c => <TableCell key={c.key}>{c.cell(row)}</TableCell>)}</TableRow>) :
        <TableRow><TableCell colSpan={columns.length}>{empty ?? <EmptyState title="No results" description="No items are available for this view." />}</TableCell></TableRow>}
      </TableBody>
    </Table>
  </div>
}

export function FilterBar(props: ComponentProps<'div'>) { return <div {...props} className={`fx-filters ${props.className ?? ''}`} /> }
export function SearchField({ label = 'Search', ...props }: ComponentProps<typeof Input> & { label?: string }) {
  const generatedId = useId()
  const id = props.id ?? generatedId
  return <div className="fx-search"><Label htmlFor={id}>{label}</Label><div className="relative">
    <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
    <Input {...props} id={id} type="search" className={`pl-9 ${props.className ?? ''}`} />
  </div></div>
}
export function Pagination({ page, pages, previousUrl, nextUrl }: { page: number; pages: number; previousUrl: string | null; nextUrl: string | null }) {
  return <nav aria-label="Pagination" className="fx-pagination">
    {previousUrl ? <Button variant="outline" asChild><a href={previousUrl}><ChevronLeft aria-hidden="true" />Previous</a></Button> : <Button variant="outline" disabled><ChevronLeft aria-hidden="true" />Previous</Button>}
    <span aria-current="page">Page {page} of {Math.max(1, pages)}</span>
    {nextUrl ? <Button variant="outline" asChild><a href={nextUrl}>Next<ChevronRight aria-hidden="true" /></a></Button> : <Button variant="outline" disabled>Next<ChevronRight aria-hidden="true" /></Button>}
  </nav>
}
/** Labels and tones are presentation inputs, never inferred business statuses. */
export function StatusBadge({ label, tone = 'neutral' }: { label: string; tone?: 'info' | 'warn' | 'progress' | 'ready' | 'neutral' | 'success' | 'danger' }) {
  return <Badge variant="outline" className="lx-status whitespace-normal h-auto" data-tone={tone}>{label}</Badge>
}
