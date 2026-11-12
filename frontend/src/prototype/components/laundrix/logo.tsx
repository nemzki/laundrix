import { WashingMachine } from 'lucide-react'
import { cn } from '@prototype/lib/utils'

/**
 * Temporary Laundrix logo placeholder. Replace the mark with the official
 * Laundrix logo asset (e.g. /public/laundrix-logo.svg) when available.
 */
export function LaundrixLogo({ className, showTagline = true }: { className?: string; showTagline?: boolean }) {
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <WashingMachine className="size-4.5" aria-hidden="true" />
      </div>
      <div className="flex min-w-0 flex-col leading-none">
        <span className="text-[15px] font-semibold tracking-tight text-foreground">Laundrix</span>
        {showTagline && <span className="mt-1 truncate text-[11px] text-muted-foreground">Wash Up! Laundry Shop</span>}
      </div>
    </div>
  )
}
