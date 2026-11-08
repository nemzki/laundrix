import { useId, type ReactNode } from 'react'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'

/** Explicit control ID makes labels, hints and server errors usable for any native/shadcn control. */
export function FormField({ id, label, hint, error, required, children }: {
  id: string; label: string; hint?: string; error?: string; required?: boolean
  children: (props: { id: string; 'aria-describedby'?: string; 'aria-invalid': boolean; required?: boolean }) => ReactNode
}) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') || undefined
  return <div className="fx-field"><Label htmlFor={id}>{label}{required && <span aria-hidden="true"> *</span>}</Label>
    {children({ id, 'aria-describedby': describedBy, 'aria-invalid': Boolean(error), required })}
    {hint && <p id={`${id}-hint`} className="text-sm text-muted-foreground">{hint}</p>}
    {error && <p id={`${id}-error`} className="text-sm text-destructive" role="alert">{error}</p>}
  </div>
}
export function TextField({ label, hint, error, ...props }: React.ComponentProps<typeof Input> & { label: string; hint?: string; error?: string }) {
  const generatedId = useId()
  return <FormField id={props.id ?? generatedId} label={label} hint={hint} error={error} required={props.required}>
    {accessibility => <Input {...props} {...accessibility} />}
  </FormField>
}
