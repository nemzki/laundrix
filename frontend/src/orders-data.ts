export interface OrderSummary {
  reference: string; customer: string; contact: string; created: string; createdShort: string
  total: string; paid: string; balance: string; balanceNote: string
  laundry: string; laundryTone: string; payment: string; paymentTone: string
  awaiting: boolean; detailUrl: string; stubUrl: string
}
export interface OrdersPageData {
  orders: OrderSummary[]
  filters: { value: string; label: string; count: number; url: string }[]
  term: string; status: string; indexUrl: string; newOrderUrl: string; fallbackUrl: string
  total: number; page: number; pages: number
  previousUrl: string | null; nextUrl: string | null
}
/** Fail back to Jinja rather than mounting incomplete or incompatible data. */
export function parseOrdersData(value: unknown): OrdersPageData {
  if (!value || typeof value !== 'object') throw new Error('Missing order data')
  const data = value as OrdersPageData
  if (!Array.isArray(data.orders) || !Array.isArray(data.filters) ||
      !Number.isInteger(data.total) || !Number.isInteger(data.page) ||
      !Number.isInteger(data.pages) || typeof data.term !== 'string' ||
      typeof data.status !== 'string') throw new Error('Invalid order data')
  const validUrl = (url: unknown) => {
    if (typeof url !== 'string') return false
    const parsed = new URL(url, window.location.href)
    return parsed.origin === window.location.origin && /^https?:$/.test(parsed.protocol)
  }
  if (![data.indexUrl, data.newOrderUrl, data.fallbackUrl, ...data.filters.map(f => f.url),
        ...data.orders.flatMap(o => [o.detailUrl, o.stubUrl]),
        ...[data.previousUrl, data.nextUrl].filter(url => url !== null)].every(validUrl)) {
    throw new Error('Invalid order destination')
  }
  for (const order of data.orders) {
    const fields = ['reference', 'customer', 'contact', 'created', 'createdShort', 'total',
      'paid', 'balance', 'balanceNote', 'laundry', 'laundryTone', 'payment', 'paymentTone'] as const
    if (!fields.every(key => typeof order[key] === 'string') || typeof order.awaiting !== 'boolean') {
      throw new Error('Invalid order summary')
    }
  }
  if (!data.filters.every(f => typeof f.value === 'string' && typeof f.label === 'string' && Number.isInteger(f.count))) {
    throw new Error('Invalid status filters')
  }
  return data
}
