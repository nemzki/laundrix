import { LoaderCircle, CircleAlert, Inbox, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ReactNode } from 'react'

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return <div role="status" className="fx-state"><LoaderCircle className="animate-spin" aria-hidden="true" /><p>{label}</p></div>
}
export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return <div className="fx-state"><Inbox aria-hidden="true" /><h2 className="font-semibold">{title}</h2>{description && <p className="text-muted-foreground">{description}</p>}{action}</div>
}
export function ErrorState({ title = 'Unable to load this view', description, retry }: { title?: string; description: string; retry?: () => void }) {
  return <div className="fx-state" role="alert"><CircleAlert aria-hidden="true" /><h2 className="font-semibold">{title}</h2><p>{description}</p>
    {retry && <Button type="button" variant="outline" onClick={retry}>Try again</Button>}</div>
}
export interface ToastMessage { id: string; message: string; tone?: 'info' | 'error' }
/** Controlled, persistent until dismissed; no injected styles/timers or automatic success claims. */
export function ToastNotifications({ messages, onDismiss }: { messages: ToastMessage[]; onDismiss: (id: string) => void }) {
  return <div className="fx-toasts" aria-label="Notifications" aria-live="polite" aria-relevant="additions text">
    {messages.map(message => <div className="fx-toast" key={message.id} role={message.tone === 'error' ? 'alert' : 'status'}>
      <p>{message.message}</p><Button size="icon" variant="ghost" aria-label="Dismiss notification" onClick={() => onDismiss(message.id)}><X aria-hidden="true" /></Button>
    </div>)}
  </div>
}
