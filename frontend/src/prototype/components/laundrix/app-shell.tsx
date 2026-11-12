import { useId, type ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarGroupLabel,
  SidebarHeader, SidebarInset, SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarProvider, SidebarTrigger, useSidebar } from '@prototype/components/ui/sidebar'
import { Separator } from '@prototype/components/ui/separator'
import { LaundrixLogo } from './logo'

export type WorkspaceRole = 'admin' | 'staff'
export interface NavigationSection {
  label: string
  items: { label: string; href: string; icon: LucideIcon; active?: boolean; roles: WorkspaceRole[] }[]
}

/** Derived from the reference AppSidebar. No mock identity, logout or business store. */
export function AppSidebar({ role, sections, account, brand }: {
  role: WorkspaceRole; sections: NavigationSection[]; account?: ReactNode; brand?: ReactNode
}) {
  const { setOpenMobile, isMobile } = useSidebar()
  return <Sidebar><SidebarHeader className="h-14 justify-center border-b px-4">{brand ?? <LaundrixLogo />}</SidebarHeader>
    <SidebarContent className="gap-0 py-2"><nav aria-label="Main navigation">
      {sections.map(section => {
        const items = section.items.filter(item => item.roles.includes(role))
        if (!items.length) return null
        return <SidebarGroup key={section.label} className="py-1.5"><SidebarGroupLabel className="text-[11px] font-semibold tracking-wider uppercase">{section.label}</SidebarGroupLabel>
          <SidebarGroupContent><SidebarMenu>{items.map(item => <SidebarMenuItem key={item.href}>
            <SidebarMenuButton isActive={item.active} tooltip={isMobile ? undefined : item.label} render={<a href={item.href} aria-current={item.active ? 'page' : undefined} onClick={() => setOpenMobile(false)} />}>
              <item.icon aria-hidden="true" /><span>{item.label}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>)}</SidebarMenu></SidebarGroupContent>
        </SidebarGroup>
      })}
    </nav></SidebarContent>
    {account && <SidebarFooter className="border-t">{account}</SidebarFooter>}
  </Sidebar>
}

/** Same reference header structure; content is supplied by the authorized caller. */
export function AppHeader({ section, title, actions }: { section?: string; title: string; actions?: ReactNode }) {
  return <header className="sticky top-0 z-10 flex min-h-14 shrink-0 items-center gap-2 border-b bg-background/90 px-4 py-2 backdrop-blur md:px-6 lg:px-8">
    <SidebarTrigger className="-ml-1.5" aria-label="Toggle navigation" />
    <Separator orientation="vertical" className="mr-1 h-4 data-vertical:self-center" />
    <nav aria-label="Breadcrumb" className="min-w-0 flex-1"><ol className="flex items-center gap-1.5 text-sm">
      {section && <><li className="hidden text-muted-foreground sm:block">{section}</li><li aria-hidden="true" className="hidden sm:block">/</li></>}
      <li className="truncate font-medium">{title}</li>
    </ol></nav>{actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
  </header>
}

/** Presentation only. Role filtering never replaces Flask's authorization checks. */
export function AppShell({ role, sections, account, header, children, brand }: {
  role: WorkspaceRole; sections: NavigationSection[]; account?: ReactNode
  header: ReactNode; children: ReactNode; brand?: ReactNode
}) {
  const mainId = useId()
  return <SidebarProvider><a href={`#${mainId}`} className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:rounded-md focus:bg-background focus:p-3">Skip to content</a>
    <AppSidebar role={role} sections={sections} account={account} brand={brand} />
    <SidebarInset className="min-w-0" data-role={role}>{header}<main id={mainId} tabIndex={-1} className="min-w-0 flex-1">{children}</main></SidebarInset>
  </SidebarProvider>
}
