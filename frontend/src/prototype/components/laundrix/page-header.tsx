import { cn } from '@prototype/lib/utils'

export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between', className)}>
      <div className="flex min-w-0 flex-col gap-1">
        <h1 className="text-xl font-semibold tracking-tight text-balance text-foreground md:text-2xl">{title}</h1>
        {description && <p className="text-sm text-pretty text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function PageContainer({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('mx-auto flex w-full max-w-[1440px] flex-col gap-6 p-4 md:p-6 lg:px-8', className)}>{children}</div>
}
