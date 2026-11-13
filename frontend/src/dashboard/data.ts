import { z } from 'zod'
// Keep data validation compatible with Flask's existing script-src 'self'.
z.config({ jitless: true })
const url = z.string().refine(value => {
  try { const parsed = new URL(value, location.href); return parsed.origin === location.origin && ['http:', 'https:'].includes(parsed.protocol) } catch { return false }
}, 'Expected existing same-origin destination')
const icon = z.enum(['dashboard', 'plus', 'orders', 'wallet', 'users', 'services', 'staff', 'receipt', 'chart', 'settings', 'processing', 'ready', 'alert'])
const schema = z.object({
  role: z.enum(['admin', 'staff']), title: z.string(), description: z.string(), csrf: z.string().min(1),
  user: z.object({ name: z.string(), initials: z.string(), picture: z.string(), label: z.string() }),
  metrics: z.array(z.object({ key: z.string(), label: z.string(), value: z.string(), group: z.string(), icon })),
  recent: z.array(z.object({ reference: z.string(), customer: z.string(), total: z.string(), status: z.string(), value: z.string(), tone: z.enum(['info', 'warn', 'progress', 'ready', 'neutral', 'success']), url })),
  popular: z.array(z.object({ name: z.string(), count: z.number().int().nonnegative() })),
  navigation: z.array(z.object({ label: z.string(), items: z.array(z.object({ label: z.string(), url, icon, active: z.boolean() })) })),
  urls: z.object({ home: url, newOrder: url, orders: url, customers: url, logout: url, fallback: url, brand: url, settings: url }),
})
export type DashboardData = z.infer<typeof schema>
export type DashboardIcon = z.infer<typeof icon>

export function parseDashboard(value: unknown): DashboardData {
  const data = schema.parse(value)
  const keys = data.role === 'admin'
    ? ['total_orders', 'today', 'processing', 'ready', 'awaiting_receipt', 'owing_count', 'owing_total', 'collected_today']
    : ['today', 'pending', 'processing', 'ready', 'awaiting_receipt', 'owing_count', 'owing_total']
  if (data.metrics.length !== keys.length || new Set(data.metrics.map(metric => metric.key)).size !== keys.length ||
    !keys.every(key => data.metrics.some(metric => metric.key === key)) || (data.role === 'staff' && data.popular.length)) {
    throw new Error('Incomplete or incompatible dashboard context')
  }
  return data
}
