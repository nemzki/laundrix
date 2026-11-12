import * as React from 'react'
import { Switch as Primitive } from 'radix-ui'
import { cn } from '@/lib/utils'

function Switch({ className, ...props }: React.ComponentProps<typeof Primitive.Root>) {
  return <Primitive.Root data-slot="switch" className={cn('inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-transparent bg-slate-300 transition-colors outline-none data-[state=checked]:bg-blue-600 focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50',className)} {...props}>
    <Primitive.Thumb className="pointer-events-none block size-4 rounded-full bg-white shadow-sm transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0" />
  </Primitive.Root>
}
export { Switch }
