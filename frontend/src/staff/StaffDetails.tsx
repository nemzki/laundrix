import { useRef, useState, type FormEvent } from 'react'
import { ArrowLeft, Check, ChevronDown, Link2, LoaderCircle, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { fetchDetail, submitAction, type Action, type Details, type Enrollment } from './api'
import { EnrollmentDialog } from './EnrollmentDialog'
import { initials, Status } from './Staff'

const destructiveLabels = {
  'Reject Account': 'Reject registration',
  'Suspend Account': 'Suspend account',
  'Deactivate Account': 'Deactivate account',
}
const isDestructive = (action: Action) => Object.hasOwn(destructiveLabels, action.label)
const destructiveHeading = (action: Action) => destructiveLabels[action.label as keyof typeof destructiveLabels]
const card = 'min-w-0 gap-4 border border-border bg-card p-5 ring-0 sm:p-6'
const heading = 'm-0 text-base leading-6 font-semibold text-foreground'
const muted = 'text-[var(--lx-paint-secondary,var(--lx-muted))]'

type StepState = 'Completed' | 'Current' | 'Upcoming' | 'Failed' | 'Unavailable'
const stepStyle: Record<StepState, string> = {
  Completed: 'border-[var(--lx-paint-green-border,var(--lx-border))] bg-[var(--lx-paint-green-bg,var(--lx-success-soft))] text-[var(--lx-paint-green-ink,var(--lx-success))]',
  Current: 'border-[var(--lx-paint-amber-ink,var(--lx-warn))] bg-[var(--lx-paint-amber-bg,var(--lx-warn-soft))] text-[var(--lx-paint-amber-ink,var(--lx-warn))]',
  Upcoming: 'border-border bg-[var(--lx-paint-muted,var(--lx-bg))] text-[var(--lx-paint-secondary,var(--lx-muted))]',
  Failed: 'border-[var(--lx-paint-red-border,var(--lx-border))] bg-[var(--lx-paint-red-bg,var(--lx-danger-soft))] text-[var(--lx-paint-red-ink,var(--lx-danger))]',
  Unavailable: 'border-border bg-[var(--lx-paint-muted,var(--lx-bg))] text-[var(--lx-paint-secondary,var(--lx-muted))]',
}

function VerificationTracker({ account }: { account: Details }) {
  const verified = account.identity === 'Verified'
  const approved = account.approved !== 'Not yet' && Boolean(account.approved)
  const active = account.status === 'active'
  const pending = account.status === 'pending_verification'
  const rejected = account.status === 'rejected'
  const inactive = account.status === 'deactivated' || account.status === 'suspended'
  const verificationFailed = ['Rejected', 'Error'].includes(account.identity)
  const steps: { label: string; state: StepState; value: string }[] = [
    { label: 'Account Created', state: 'Completed', value: account.created },
    {
      label: 'ID Verification',
      state: verified ? 'Completed' : verificationFailed ? 'Failed' : pending ? 'Current' : 'Unavailable',
      value: [account.identity, account.identityDecision].filter(Boolean).join(' · '),
    },
    {
      label: 'Approval',
      // An active account may predate recorded approvals.
      state: approved ? 'Completed' : account.status === 'pending_approval' ? 'Current' : rejected && verified ? 'Failed' : active || inactive || rejected ? 'Unavailable' : 'Upcoming',
      value: rejected && verified && !approved ? account.label : active && !approved ? 'Not recorded' : account.approved,
    },
    {
      label: 'Active',
      state: active ? 'Completed' : inactive || rejected ? 'Unavailable' : 'Upcoming',
      value: inactive || rejected ? account.label : account.lastLogin === 'Never' ? 'Never signed in' : account.lastLogin,
    },
  ]

  return (
    <Card role="region" aria-label="Verification progress" className={card}>
      <ol className="m-0 grid list-none gap-4 p-0 sm:grid-cols-4 sm:gap-0">
        {steps.map(({ label, state, value }, index) => (
          <li key={label} aria-current={state === 'Current' ? 'step' : undefined} data-step-state={state}
            className="relative grid min-w-0 grid-cols-[2.25rem_minmax(0,1fr)] items-start gap-x-3 sm:flex sm:flex-col sm:items-center sm:px-2 sm:text-center">
            {index < steps.length - 1 && (
              <span aria-hidden="true" className="absolute top-9 left-[1.0625rem] h-[calc(100%-1.25rem)] w-px bg-border sm:top-[1.0625rem] sm:left-1/2 sm:h-px sm:w-full" />
            )}
            <span aria-hidden="true" className={`relative grid size-9 place-items-center rounded-full border text-xs font-semibold ${stepStyle[state]}`}>
              {state === 'Completed' ? <Check size={16}/> : state === 'Failed' ? <X size={16}/> : index + 1}
            </span>
            <div className="min-w-0 sm:pt-2">
              <div className="text-sm leading-5 font-semibold">{label}</div>
              <div className={`mt-1 text-xs leading-4 wrap-anywhere ${muted}`}>{state} — {value}</div>
            </div>
          </li>
        ))}
      </ol>
    </Card>
  )
}

function AccountDetails({ account }: { account: Details }) {
  const withActor = (value: string, actor: string) => actor ? `${value} by ${actor}` : value
  const columns = [
    [
      ['Role', 'Staff'],
      ['Created', account.created],
      ['Approved', withActor(account.approved, account.approver)],
      ['Enrollment Link', account.enrollment],
    ],
    [
      ['Identity Verification', <div className="flex flex-wrap items-center gap-2">
        <span className="staff-identity" data-tone={account.identity === 'Verified' ? 'success' : ['Action required', 'In review', 'Error'].includes(account.identity) ? 'warn' : account.identity === 'In progress' ? 'progress' : 'neutral'}>{account.identity}</span>
        {account.identityDecision && <span className={`text-xs ${muted}`}>{account.identityDecision}</span>}
      </div>],
      ['Last Sign-in', account.lastLogin],
      ['Last Status Change', withActor(account.changed, account.changedBy)],
      ...(account.reason ? [['Reason', account.reason]] : []),
    ],
  ]
  return (
    <Card className={card} role="region" aria-labelledby="staff-account-details">
      <h2 id="staff-account-details" className={heading}>Account details</h2>
      <div className="grid gap-4 md:grid-cols-2 md:gap-6">
        {columns.map((facts, index) => (
          <dl key={index} className="m-0 grid content-start gap-4">
            {facts.map(([label, value]) => (
              <div key={String(label)} className="min-w-0">
                <dt className={`text-xs leading-4 font-medium ${muted}`}>{label}</dt>
                <dd className="mt-1 mb-0 text-sm leading-5 wrap-anywhere">{value}</dd>
              </div>
            ))}
          </dl>
        ))}
      </div>
    </Card>
  )
}

function RecentActivity({ activity }: { activity: Details['activity'] }) {
  return (
    <Card className={card}>
      <h2 className={heading}>Recent activity</h2>
      {activity.length ? (
        <ol className="m-0 ml-1 list-none p-0">
          {activity.map((event, index) => (
            <li key={`${event.time}-${index}`} className="relative border-l border-border pb-4 pl-4 last:border-transparent last:pb-0">
              <span aria-hidden="true" className="absolute top-1.5 -left-[4.5px] size-2 rounded-full bg-primary"/>
              <div className="text-sm font-semibold wrap-anywhere">{event.label}{!event.success && <span className="ml-2 text-xs text-destructive">Failed</span>}</div>
              <div className={`mt-0.5 text-xs wrap-anywhere ${muted}`}>{event.time}{event.actor && ` · ${event.actor}`}</div>
              {event.detail && <p className={`mt-1 mb-0 text-sm wrap-anywhere ${muted}`}>{event.detail}</p>}
            </li>
          ))}
        </ol>
      ) : <p className={`m-0 ${muted}`}>No activity recorded yet.</p>}
    </Card>
  )
}

export function StaffDetails({ initial, index }: { initial: Details; index: string }) {
  const [account, setAccount] = useState(initial)
  const [operation, setOperation] = useState<{ action: Action; reason: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [refreshError, setRefreshError] = useState('')
  const [link, setLink] = useState<Enrollment | null>(null)
  const [notice, setNotice] = useState('')
  const trigger = useRef<HTMLElement | null>(null)
  const profile = useRef<HTMLHeadingElement>(null)
  const lock = useRef(false)
  const openingLink = useRef(false)
  const nextActions = account.actions.filter(action => !isDestructive(action))
  const dangerActions = account.actions.filter(isDestructive)
  const canGenerate = nextActions.some(action => action.label === 'Generate New Link')
  const confirmingLink = operation?.action.label === 'Generate New Link'
  const pendingEnrollment = account.status === 'pending_verification' && canGenerate
  const nextHeading = pendingEnrollment ? 'Send an enrollment link'
    : nextActions[0]?.label === 'Approve Account' ? 'Approve this account'
    : nextActions[0]?.label === 'Reactivate Account' ? 'Reactivate this account'
    : canGenerate ? 'Send a re-verification link' : account.label
  const nextDescription = pendingEnrollment
    ? account.enrollment === 'None active'
      ? 'There is no active link, so this staff member cannot verify their identity yet.'
      : 'An enrollment link is active. You can issue a replacement if the staff member needs a new one.'
    : canGenerate ? 'Issue a one-time link so this staff member can verify their identity again.'
    : nextActions[0]?.description || 'No next step is available for this account.'

  function restoreFocus(event: Event) {
    event.preventDefault()
    if (openingLink.current) return
    const button = trigger.current
    const target = button?.isConnected && !button.matches(':disabled') ? button : profile.current
    target?.focus()
  }

  function choose(action: Action, reason: string, button: HTMLElement) {
    trigger.current = button
    setError('')
    setNotice('')
    setOperation({ action, reason })
  }

  async function refreshDetails() {
    try {
      setAccount(await fetchDetail(location.href))
      setRefreshError('')
    } catch {
      setRefreshError('The action succeeded, but the account details could not be refreshed.')
    }
  }

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!operation || lock.current) return
    const { action, reason } = operation
    if (action.reason && reason.trim().length < action.min) {
      setError(`Enter a reason of at least ${action.min} characters.`)
      return
    }
    lock.current = true
    setBusy(true)
    setError('')
    try {
      const result = await submitAction(action, reason)
      if ('link' in result) {
        openingLink.current = true
        setLink(result.link)
      } else {
        setAccount(result.details)
        setRefreshError('')
        setNotice('Account updated.')
      }
      setOperation(null)
      if ('link' in result) await refreshDetails()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Action was not confirmed.')
    } finally {
      lock.current = false
      setBusy(false)
    }
  }

  return (
    <div className="grid min-w-0 gap-4">
      <header className="mb-2 flex min-w-0 flex-wrap items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <span aria-hidden="true" className="staff-avatar staff-avatar-large size-12 rounded-full border-[var(--lx-paint-blue-border,var(--lx-border))]! bg-[var(--lx-paint-blue-bg,var(--lx-primary-soft))]! text-[var(--lx-paint-blue-ink,var(--lx-primary-hover))]!">{initials(account.name)}</span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h1 ref={profile} tabIndex={-1} className="m-0 text-2xl leading-8 font-semibold tracking-tight wrap-anywhere text-foreground">{account.name}</h1>
              <Status value={account.status} label={account.label}/>
            </div>
            <p className={`mt-1 mb-0 text-sm wrap-anywhere ${muted}`}>{account.email} <span aria-hidden="true">·</span> Staff</p>
          </div>
        </div>
        <Button variant="outline" className="max-md:min-h-11!" asChild><a href={index}><ArrowLeft aria-hidden="true"/>All Staff</a></Button>
      </header>
      <VerificationTracker account={account}/>
      {notice && <p role="status" className="m-0 text-sm text-[var(--lx-paint-green-ink,var(--lx-success))]">{notice}</p>}
      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="contents xl:flex xl:min-w-0 xl:flex-col xl:gap-4">
          <div className="order-1 min-w-0 xl:order-none"><AccountDetails account={account}/></div>
          <div className="order-3 min-w-0 xl:order-none"><RecentActivity activity={account.activity}/></div>
        </div>
        <div className="contents xl:flex xl:min-w-0 xl:flex-col xl:gap-4">
          <Card className={`order-2 xl:order-none ${card} border-[var(--lx-paint-blue-border,var(--lx-primary))]`}>
            <CardHeader className="gap-2 p-0">
              <div className="text-xs font-semibold tracking-wide text-[var(--lx-paint-blue-ink,var(--lx-primary-hover))] uppercase">Next step</div>
              <h2 className={heading}>{nextHeading}</h2>
              <p className={`m-0 text-sm ${muted}`}>{nextDescription}</p>
            </CardHeader>
            {nextActions.length > 0 && (
              <CardContent className="grid gap-3 p-0">
                {nextActions.map(action => <Button key={action.url} className="w-full max-md:min-h-11!" disabled={busy || Boolean(refreshError)} onClick={event => choose(action, '', event.currentTarget)}>
                  {action.label === 'Generate New Link' && <Link2 aria-hidden="true"/>}{action.label}
                </Button>)}
                {canGenerate && <p className={`m-0 text-xs leading-4 ${muted}`}>One-time link. Generating a new one stops any older link from working.</p>}
              </CardContent>
            )}
            {refreshError && <div role="alert" className="grid gap-2 text-sm"><span>{refreshError}</span><Button variant="outline" onClick={refreshDetails}>Retry refresh</Button></div>}
          </Card>
          {dangerActions.length > 0 && (
            <Card className={`order-4 xl:order-none ${card}`}>
              <h2 className={heading}>Danger zone</h2>
              <div className="divide-y divide-border">
                {dangerActions.map(action => {
                  const title = destructiveHeading(action)
                  const description = action.label === 'Reject Account' ? 'Declines this request and disables the enrollment link.'
                    : action.label === 'Deactivate Account' ? 'Offboarding. The record stays so past orders and payments still show who handled them.'
                    : action.description
                  return (
                    <details key={action.url} className="group py-2 first:pt-0 last:pb-0">
                      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-md text-sm font-semibold text-destructive focus-visible:outline-2 focus-visible:outline-ring [&::-webkit-details-marker]:hidden">
                        {title}<ChevronDown aria-hidden="true" size={16} className="shrink-0 group-open:rotate-180"/>
                      </summary>
                      <p className={`mt-1 mb-3 text-sm ${muted}`}>{description}</p>
                      <form className="grid gap-2 pb-2" onSubmit={event => {
                        event.preventDefault()
                        const reason = String(new FormData(event.currentTarget).get('reason') ?? '')
                        const button = (event.nativeEvent as SubmitEvent).submitter as HTMLElement | null
                        choose(action, reason, button ?? event.currentTarget.querySelector('button')!)
                      }}>
                        {action.reason && <>
                          <Label htmlFor={`staff-${action.label}-reason`.replaceAll(' ', '-')}>Reason (required)</Label>
                          <Input id={`staff-${action.label}-reason`.replaceAll(' ', '-')} className="max-md:min-h-11!" name="reason" required minLength={action.min} maxLength={action.max}/>
                        </>}
                        <Button type="submit" variant="destructive" className="max-md:min-h-11!" disabled={busy || Boolean(refreshError)}>{action.label}</Button>
                      </form>
                    </details>
                  )
                })}
              </div>
            </Card>
          )}
        </div>
      </div>
      <Dialog open={Boolean(operation)} onOpenChange={open => { if (!open && !busy) setOperation(null) }}>
        <DialogContent className={confirmingLink ? 'staff-dialog staff-confirm-dialog' : 'staff-dialog'} onCloseAutoFocus={restoreFocus}
          onEscapeKeyDown={event => { if (busy) event.preventDefault() }}
          onPointerDownOutside={event => { if (busy) event.preventDefault() }}>
          <DialogHeader>
            <DialogTitle>{operation?.action.label}</DialogTitle>
            <DialogDescription>{operation?.action.description}</DialogDescription>
          </DialogHeader>
          <form onSubmit={confirm}>
            <div className={confirmingLink ? 'staff-form-body staff-confirm-body' : 'staff-form-body'}>
              {error && <p role="alert" className="staff-error">{error}</p>}
              {operation?.action.reason && <>
                <Label htmlFor="staff-detail-confirm-reason">Reason (required)</Label>
                <Input id="staff-detail-confirm-reason" required minLength={operation.action.min} maxLength={operation.action.max}
                  value={operation.reason} disabled={busy} onChange={event => {
                    setOperation({ ...operation, reason: event.target.value })
                    setError('')
                  }}/>
              </>}
            </div>
            <DialogFooter className={confirmingLink ? 'staff-form-footer staff-confirm-footer' : 'staff-form-footer'}>
              <Button type="button" variant="outline" disabled={busy} onClick={() => setOperation(null)}>Cancel</Button>
              <Button type="submit" variant={operation && isDestructive(operation.action) ? 'destructive' : 'default'} disabled={busy}>
                {busy && <LoaderCircle aria-hidden="true" className="animate-spin"/>}
                Confirm
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <EnrollmentDialog link={link} onClose={() => { openingLink.current = false; setLink(null) }} restoreFocus={restoreFocus}/>
    </div>
  )
}
