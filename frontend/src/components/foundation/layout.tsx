import { useId, useState, type ReactNode } from 'react'
import { Menu, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { cn } from '@/lib/utils'
import { FoundationPortalTheme } from '@/lib/portal-theme'

export interface NavigationGroup {
  label: string
  items: { label: string; href: string; icon: LucideIcon; active?: boolean }[]
}

/** Supply only destinations authorized by Flask. This component grants no permissions. */
export function SidebarNavigation({ groups, onNavigate }: { groups: NavigationGroup[]; onNavigate?: () => void }) {
  return <nav aria-label="Main navigation" className="fx-nav">
    {groups.map(group => <section key={group.label} aria-label={group.label}>
      <p className="fx-nav-label">{group.label}</p>
      {group.items.map(({ icon: Icon, ...item }) => <a key={item.href} href={item.href}
        aria-current={item.active ? 'page' : undefined} onClick={onNavigate} className="fx-nav-link">
        <Icon size={18} aria-hidden="true" /><span>{item.label}</span>
      </a>)}
    </section>)}
  </nav>
}

export function AppHeader({ children, navigation }: { children: ReactNode; navigation?: ReactNode }) {
  return <header className="fx-header">{navigation}<div className="min-w-0 flex-1">{children}</div></header>
}

/** Deliberately accepts the existing account/logout UI instead of handling authentication. */
export function AppShell({ role, brand, groups, account, header, children }: {
  role: 'admin' | 'staff'; brand: ReactNode; groups: NavigationGroup[]; account?: ReactNode
  header: ReactNode; children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const mainId = useId()
  return <FoundationPortalTheme><div className="lx-react lx-foundation fx-shell" data-role={role}>
    <a className="fx-skip" href={`#${mainId}`}>Skip to content</a>
    <aside className="fx-sidebar" aria-label={`${role === 'admin' ? 'Admin' : 'Staff'} sidebar`}>
      <div className="fx-brand">{brand}</div><SidebarNavigation groups={groups} />
      {account && <div className="fx-account">{account}</div>}
    </aside>
    <div className="fx-main">
      <AppHeader navigation={<div className="fx-mobile-menu"><Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild><Button variant="outline" size="icon" aria-label="Open navigation"><Menu aria-hidden="true" /></Button></SheetTrigger>
        <SheetContent side="left" className="fx-drawer">
          <SheetHeader><SheetTitle>Navigation</SheetTitle><SheetDescription>Internal {role === 'admin' ? 'Admin' : 'Staff'} workspace</SheetDescription></SheetHeader>
          <div className="fx-brand">{brand}</div><SidebarNavigation groups={groups} onNavigate={() => setOpen(false)} />
          {account && <div className="fx-account">{account}</div>}
        </SheetContent>
      </Sheet></div>}>{header}</AppHeader>
      <main id={mainId} tabIndex={-1} className="fx-content">{children}</main>
    </div>
  </div></FoundationPortalTheme>
}

export function PageContainer({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('fx-page', className)} {...props} />
}
export function PageHeading({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return <div className="fx-page-heading"><div className="min-w-0"><h1>{title}</h1>
    {description && <p className="text-muted-foreground mt-1">{description}</p>}</div>
    {actions && <div className="fx-actions">{actions}</div>}
  </div>
}
