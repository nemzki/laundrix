// MODAL: Show and copy the staff enrollment link
/** Present the enrollment link and provide a way to copy it. */
import { useState } from 'react'
import { Check, CircleCheck, Copy, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import type { Enrollment } from './api'

export function EnrollmentDialog({ link, onClose, restoreFocus }: {
  link: Enrollment | null
  onClose: () => void
  restoreFocus: (event: Event) => void
}) {
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState('')

  function close() {
    setCopied(false)
    setCopyError('')
    onClose()
  }

  async function copyLink() {
    if (!link) return
    setCopyError('')
    try {
      await navigator.clipboard.writeText(link.url)
      setCopied(true)
    } catch {
      const input = document.getElementById('staff-enrollment') as HTMLInputElement | null
      input?.focus()
      input?.select()
      setCopyError('Copy is unavailable here. The link is selected so you can copy it manually.')
    }
  }

  return (
    <Dialog open={Boolean(link)} onOpenChange={open => { if (!open) close() }}>
      <DialogContent className="staff-dialog staff-enrollment-dialog" onCloseAutoFocus={restoreFocus}>
        <DialogHeader>
          <DialogTitle>Enrollment Link Generated</DialogTitle>
          <DialogDescription>Share this secure, one-time link with the staff member.</DialogDescription>
        </DialogHeader>
        <div className="staff-enrollment-body">
          <section className="staff-link-success" aria-label="Link ready to share">
            <CircleCheck aria-hidden="true"/>
            <div><strong>Link Ready to Share</strong><span>{link?.staffName}</span></div>
          </section>
          <div className="staff-enrollment-field">
            <Label htmlFor="staff-enrollment">Enrollment Link</Label>
            <Input id="staff-enrollment" className="staff-enrollment-input" readOnly value={link?.url || ''} autoComplete="off" spellCheck={false}/>
            <Button className="staff-copy-link" variant="outline" onClick={copyLink}>
              {copied ? <Check aria-hidden="true"/> : <Copy aria-hidden="true"/>}
              {copied ? 'Copied' : 'Copy Link'}
            </Button>
            {copyError && <p className="staff-copy-error" role="alert">{copyError}</p>}
            <p className="staff-expiration">Expires {link?.expires}</p>
          </div>
          <section className="staff-enrollment-next">
            <h3>What Happens Next?</h3>
            <ol>{link?.instructions.map((text, index) => <li key={`${index}-${text}`}>{text}</li>)}</ol>
          </section>
          <p className="staff-link-security">
            <ShieldCheck aria-hidden="true"/>This link is single-use and stored as a hash. Share it privately; it can only be displayed once.
          </p>
        </div>
        <DialogFooter className="staff-form-footer">
          <Button variant="outline" onClick={close}>Done</Button>
          <Button asChild><a href={link?.detail}>View Account</a></Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
