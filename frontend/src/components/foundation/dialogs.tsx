import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'

export function ContentDialog({ trigger, title, description, children }: { trigger: ReactNode; title: string; description: string; children: ReactNode }) {
  return <Dialog><DialogTrigger asChild>{trigger}</DialogTrigger><DialogContent className="fx-dialog">
    <DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription>{description}</DialogDescription></DialogHeader>
    <div className="min-h-0 overflow-y-auto">{children}</div>
  </DialogContent></Dialog>
}
/** The caller owns submission, errors and closing after a real successful response. */
export function ConfirmationDialog({ open, onOpenChange, trigger, title, description, confirmLabel, onConfirm, pending = false, error, destructive = false }: {
  open: boolean; onOpenChange: (open: boolean) => void; trigger: ReactNode; title: string; description: string
  confirmLabel: string; onConfirm: () => void; pending?: boolean; error?: string; destructive?: boolean
}) {
  return <AlertDialog open={open} onOpenChange={value => { if (!pending) onOpenChange(value) }}>
    <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger><AlertDialogContent className="fx-dialog" aria-busy={pending}>
      <AlertDialogHeader><AlertDialogTitle>{title}</AlertDialogTitle><AlertDialogDescription>{description}</AlertDialogDescription></AlertDialogHeader>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      <AlertDialogFooter><AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
        <Button type="button" variant={destructive ? 'destructive' : 'default'} onClick={onConfirm} disabled={pending}>{pending ? 'Please wait…' : confirmLabel}</Button>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
}
