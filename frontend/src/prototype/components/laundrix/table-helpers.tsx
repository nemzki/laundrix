'use client'

import * as React from 'react'
import { ChevronLeft, ChevronRight, SearchIcon, SearchX } from 'lucide-react'
import { Button } from '@prototype/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@prototype/components/ui/empty'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@prototype/components/ui/input-group'
import { Skeleton } from '@prototype/components/ui/skeleton'
import { TableCell, TableRow } from '@prototype/components/ui/table'
import { cn } from '@prototype/lib/utils'

export function SearchField({
  value,
  onChange,
  placeholder,
  className,
  label = 'Search',
}: {
  value: string
  onChange: (value: string) => void
  placeholder: string
  className?: string
  label?: string
}) {
  return (
    <InputGroup className={cn('w-full sm:w-72', className)}>
      <InputGroupAddon>
        <SearchIcon aria-hidden="true" />
      </InputGroupAddon>
      <InputGroupInput
        type="search"
        aria-label={label}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </InputGroup>
  )
}

// Preserved prototype hook; business pagination must remain server-owned.
// oxlint-disable-next-line react/only-export-components
export function usePagination<T>(items: T[], pageSize = 10, resetKey?: unknown) {
  const [page, setPage] = React.useState(1)
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize))

  const [lastKey, setLastKey] = React.useState(resetKey)
  if (lastKey !== resetKey) {
    setLastKey(resetKey)
    setPage(1)
  }

  const current = Math.min(page, pageCount)
  const pageItems = items.slice((current - 1) * pageSize, current * pageSize)
  return { page: current, setPage, pageCount, pageItems, total: items.length, pageSize }
}

function pageNumbers(page: number, pageCount: number): (number | 'gap')[] {
  if (pageCount <= 7) return Array.from({ length: pageCount }, (_, index) => index + 1)
  const pages = new Set([1, pageCount, page - 1, page, page + 1])
  const sorted = [...pages].filter((value) => value >= 1 && value <= pageCount).sort((a, b) => a - b)
  const result: (number | 'gap')[] = []
  sorted.forEach((value, index) => {
    if (index > 0 && value - sorted[index - 1] > 1) result.push('gap')
    result.push(value)
  })
  return result
}

export function TablePagination({
  page,
  pageCount,
  total,
  pageSize,
  onPageChange,
  noun = 'records',
}: {
  page: number
  pageCount: number
  total: number
  pageSize: number
  onPageChange: (page: number) => void
  noun?: string
}) {
  if (total === 0) return null
  const start = (page - 1) * pageSize + 1
  const end = Math.min(page * pageSize, total)
  return (
    <div className="flex flex-col items-center justify-between gap-3 border-t px-4 py-3 sm:flex-row">
      <p className="text-sm text-muted-foreground">
        Showing <span className="font-medium text-foreground tabular-nums">{start}</span>
        {'–'}
        <span className="font-medium text-foreground tabular-nums">{end}</span> of{' '}
        <span className="font-medium text-foreground tabular-nums">{total}</span> {noun}
      </p>
      <nav aria-label="Pagination" className="flex items-center gap-1">
        <Button variant="outline" size="sm" onClick={() => onPageChange(page - 1)} disabled={page <= 1}>
          <ChevronLeft data-icon="inline-start" />
          Previous
        </Button>
        <div className="hidden items-center gap-1 md:flex">
          {pageNumbers(page, pageCount).map((value, index) =>
            value === 'gap' ? (
              <span key={`gap-${index}`} className="px-1 text-sm text-muted-foreground" aria-hidden="true">
                {'…'}
              </span>
            ) : (
              <Button
                key={value}
                variant={value === page ? 'outline' : 'ghost'}
                size="icon-sm"
                aria-current={value === page ? 'page' : undefined}
                aria-label={`Page ${value}`}
                onClick={() => onPageChange(value)}
                className="tabular-nums"
              >
                {value}
              </Button>
            ),
          )}
        </div>
        <span className="px-2 text-sm text-muted-foreground tabular-nums md:hidden">
          {page} / {pageCount}
        </span>
        <Button variant="outline" size="sm" onClick={() => onPageChange(page + 1)} disabled={page >= pageCount}>
          Next
          <ChevronRight data-icon="inline-end" />
        </Button>
      </nav>
    </div>
  )
}

export function TableSkeletonRows({ columns, rows = 8 }: { columns: number; rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, row) => (
        <TableRow key={row}>
          {Array.from({ length: columns }, (_, column) => (
            <TableCell key={column}>
              <Skeleton className={cn('h-4', column === 0 ? 'w-28' : column === columns - 1 ? 'ml-auto w-14' : 'w-24')} />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  )
}

export function TableEmptyRow({
  columns,
  title = 'No matching records',
  description = 'Try a different search term or filter.',
  icon: Icon = SearchX,
}: {
  columns: number
  title?: string
  description?: string
  icon?: React.ComponentType<{ className?: string }>
}) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={columns} className="p-0">
        <Empty className="py-12">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Icon />
            </EmptyMedia>
            <EmptyTitle>{title}</EmptyTitle>
            <EmptyDescription>{description}</EmptyDescription>
          </EmptyHeader>
        </Empty>
      </TableCell>
    </TableRow>
  )
}

