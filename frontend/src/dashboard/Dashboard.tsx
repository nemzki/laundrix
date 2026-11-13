import { useLayoutEffect, useRef } from 'react'
import { LayoutDashboard, Plus, ClipboardList, Wallet, Users, Shirt, UserCog, Receipt, ChartNoAxesCombined, Settings,
  LoaderCircle, PackageCheck, TriangleAlert, LogOut, MoreHorizontal } from 'lucide-react'
import { AppShell, AppHeader, type NavigationSection } from '@prototype/components/laundrix/app-shell'
import { Card } from '@prototype/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@prototype/components/ui/table'
import { Button } from '@prototype/components/ui/button'
import { TooltipProvider } from '@prototype/components/ui/tooltip'
import { useSidebar } from '@prototype/components/ui/sidebar'
import type { DashboardData, DashboardIcon } from './data'

const icons = { dashboard: LayoutDashboard, plus: Plus, orders: ClipboardList, wallet: Wallet, users: Users,
  services: Shirt, staff: UserCog, receipt: Receipt, chart: ChartNoAxesCombined, settings: Settings,
  processing: LoaderCircle, ready: PackageCheck, alert: TriangleAlert } satisfies Record<DashboardIcon, React.ComponentType<{ size?: number; 'aria-hidden'?: boolean }>>

function Account({ data }: { data: DashboardData }) {
  return <div className="dashboard-account"><div className="dashboard-user">
    {data.user.picture ? <img src={data.user.picture} alt="" width={36} height={36} referrerPolicy="no-referrer" /> : <span className="dashboard-avatar" aria-hidden="true">{data.user.initials}</span>}
    <div><strong>{data.user.name}</strong><span>{data.user.label}</span></div>
    <a className="lx-personal-settings-link" href={data.urls.settings} title="Personal Settings" aria-label="Personal Settings" data-personal-settings-link><Settings size={18} aria-hidden="true" /></a>
  </div><form method="post" action={data.urls.logout}><input type="hidden" name="csrf_token" value={data.csrf} />
    <Button type="submit" variant="outline" className="dashboard-logout"><LogOut aria-hidden="true" />Logout</Button>
  </form></div>
}
function BottomNavigation({ data }: { data: DashboardData }) {
  const { setOpenMobile } = useSidebar()
  return <nav className="dashboard-bottom-nav" aria-label="Primary mobile navigation">
    <a href={data.urls.home} aria-current="page"><LayoutDashboard aria-hidden="true" /><span>Dashboard</span></a>
    <a href={data.urls.orders}><ClipboardList aria-hidden="true" /><span>Orders</span></a>
    <a href={data.urls.newOrder}><Plus aria-hidden="true" /><span>New Order</span></a>
    <a href={data.urls.customers}>{data.role === 'admin' ? <Users aria-hidden="true" /> : <Wallet aria-hidden="true" />}<span>{data.role === 'admin' ? 'Customers' : 'Balances'}</span></a>
    <button type="button" onClick={() => setOpenMobile(true)}><MoreHorizontal aria-hidden="true" /><span>More</span></button>
  </nav>
}
function IdentitySlot({ element }: { element: HTMLElement | null }) {
  const host = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => { if (element && host.current) host.current.append(element) }, [element])
  return <div ref={host} />
}
function RecentOrders({ data }: { data: DashboardData }) {
  const status = (row: DashboardData['recent'][number]) => <span className="dashboard-status" data-tone={row.tone} data-laundry-status={row.value}>{row.status}</span>
  return <Card className="dashboard-card dashboard-panel" aria-label="Recent Orders"><div className="dashboard-panel-heading"><h2>Recent Orders</h2><a href={data.urls.orders}>View All</a></div>
    {data.recent.length ? <><div className="dashboard-recent-desktop"><Table className="dashboard-table"><caption className="sr-only">Recent Orders</caption>
      <TableHeader><TableRow><TableHead scope="col">{data.role === 'admin' ? 'Order Reference' : 'Reference'}</TableHead><TableHead scope="col">Customer</TableHead><TableHead scope="col" className="dashboard-currency">Total</TableHead><TableHead scope="col">Status</TableHead></TableRow></TableHeader>
      <TableBody>{data.recent.map(row => <TableRow key={row.reference}><TableCell><a className="dashboard-reference" href={row.url}>{row.reference}</a></TableCell><TableCell>{row.customer}</TableCell><TableCell className="dashboard-currency">{row.total}</TableCell><TableCell>{status(row)}</TableCell></TableRow>)}</TableBody>
    </Table></div><div className="dashboard-recent-mobile">{data.recent.map(row => <article key={row.reference}><a className="dashboard-reference" href={row.url}>{row.reference}</a><p>{row.customer}</p><p>Total <strong>{row.total}</strong></p>{status(row)}</article>)}</div></> :
      <div className="dashboard-empty"><strong>No orders yet</strong><p>Create the first order to see activity here.</p></div>}
  </Card>
}
export function Dashboard({ data, identity, onReady }: { data: DashboardData; identity: HTMLElement | null; onReady: () => void }) {
  useLayoutEffect(onReady, [onReady])
  const navigation: NavigationSection[] = data.navigation.map(section => ({ label: section.label,
    items: section.items.map(item => ({ label: item.label, href: item.url, icon: icons[item.icon], active: item.active, roles: [data.role] })) }))
  const groups = [...new Set(data.metrics.map(metric => metric.group))]
  return <TooltipProvider><AppShell role={data.role} sections={navigation} account={<Account data={data} />}
    brand={<a className="dashboard-brand" href={data.urls.home}><img src={data.urls.brand} alt="Laundrix" width={34} height={40} /><strong>Laundrix</strong></a>}
    header={<AppHeader section="Overview" title={data.title} />}>
    <div className="dashboard-content">{data.role === 'staff' && <IdentitySlot element={identity} />}
      <div className="dashboard-heading"><div><h1>{data.title}</h1><p>{data.description}</p></div>
        <Button className="dashboard-primary" nativeButton={false} render={<a href={data.urls.newOrder} />}><Plus aria-hidden="true" />New Order</Button>
      </div>
      {groups.map(group => <section className="dashboard-group" key={group} aria-label={group}><h2>{group}</h2>
        <div className={`dashboard-metrics${group === 'Order Overview' ? ' dashboard-metrics-two' : ''}`}>
          {data.metrics.filter(metric => metric.group === group).map(metric => {
            const Icon = icons[metric.icon]
            return <Card className="dashboard-card dashboard-metric" key={metric.key} data-metric={metric.key}>
              <div><p className="dashboard-metric-label">{metric.label}</p><p className="dashboard-metric-value">{metric.value}</p></div><span className="dashboard-metric-icon"><Icon size={18} aria-hidden={true} /></span>
            </Card>
          })}
        </div>
      </section>)}
      <div className={`dashboard-panels${data.role === 'staff' ? ' dashboard-panels-single' : ''}`}><RecentOrders data={data} />
        {data.role === 'admin' && <Card className="dashboard-card dashboard-panel" aria-label="Popular Services"><div className="dashboard-panel-heading"><h2>Popular Services</h2></div>
          {data.popular.length ? <ul className="dashboard-popular">{data.popular.map((item, index) => <li key={`${item.name}-${index}`}><span>{item.name}</span><span>{item.count} line{item.count === 1 ? '' : 's'}</span></li>)}</ul> :
            <div className="dashboard-empty"><strong>No data yet</strong><p>Popular services appear once orders exist.</p></div>}
        </Card>}
      </div><a className="dashboard-fallback" href={data.urls.fallback}>Use Original Interface</a>
    </div><BottomNavigation data={data} />
  </AppShell></TooltipProvider>
}
