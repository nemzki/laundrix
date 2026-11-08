import { useId, type Key, type ReactNode } from 'react'
import { AlertCircle, LoaderCircle } from 'lucide-react'
import { Input } from '@prototype/components/ui/input'
import { Field, FieldDescription, FieldError, FieldLabel } from '@prototype/components/ui/field'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@prototype/components/ui/table'
import { Alert, AlertDescription, AlertTitle } from '@prototype/components/ui/alert'
import { Badge } from '@prototype/components/ui/badge'
import { TableEmptyRow } from './table-helpers'

export interface Column<T> { key: string; label: string; render: (item: T) => ReactNode }
/** No local business pagination, filters, sorting or calculated totals. */
export function DataTable<T>({ caption, columns, items, rowKey, busy = false }: {
  caption: string; columns: Column<T>[]; items: T[]; rowKey: (item: T) => Key; busy?: boolean
}) {
  return <div className="min-w-0 overflow-hidden rounded-xl border bg-card" aria-busy={busy}>
    <Table className="table-fixed"><caption className="sr-only">{caption}</caption>
      <TableHeader><TableRow>{columns.map(column => <TableHead scope="col" key={column.key} className="whitespace-normal px-4">{column.label}</TableHead>)}</TableRow></TableHeader>
      <TableBody>{items.length ? items.map(item => <TableRow key={rowKey(item)}>{columns.map(column => <TableCell key={column.key} className="wrap-anywhere whitespace-normal px-4">{column.render(item)}</TableCell>)}</TableRow>) : <TableEmptyRow columns={columns.length} />}</TableBody>
    </Table>
  </div>
}

export function FilterBar({ children }: { children: ReactNode }) {
  return <div className="flex min-w-0 flex-wrap items-end gap-3">{children}</div>
}
export function TextField({ label, description, error, ...props }: React.ComponentProps<typeof Input> & {
  label: string; description?: string; error?: string
}) {
  const generatedId = useId(); const id = props.id ?? generatedId
  const describedBy = [description && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') || undefined
  return <Field data-invalid={Boolean(error)}><FieldLabel htmlFor={id}>{label}</FieldLabel>
    <Input {...props} id={id} aria-invalid={Boolean(error)} aria-describedby={describedBy} />
    {description && <FieldDescription id={`${id}-hint`}>{description}</FieldDescription>}
    {error && <FieldError id={`${id}-error`} role="alert">{error}</FieldError>}
  </Field>
}
/** Labels/treatments come from the server, not the reference's simplified status model. */
export function StatusBadge({ label, className }: { label: string; className?: string }) {
  return <Badge variant="outline" className={className}>{label}</Badge>
}
export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground" role="status"><LoaderCircle className="size-4 animate-spin" aria-hidden="true" />{label}</div>
}
export function ErrorState({ title, description }: { title: string; description: string }) {
  return <Alert variant="destructive"><AlertCircle aria-hidden="true" /><AlertTitle>{title}</AlertTitle><AlertDescription>{description}</AlertDescription></Alert>
}
