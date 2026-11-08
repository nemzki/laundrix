import { useCallback, useEffect, useRef, useState } from 'react'
import { parseOrdersData, type OrdersPageData } from './orders-data'

/** Read the existing Flask HTML response; never inject its HTML or invent an API. */
export function useOrdersNavigation(initial: OrdersPageData) {
  const [data, setData] = useState(initial)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<{ controller: AbortController; url: string } | null>(null)
  const committed = useRef(window.location.href)
  const failed = useRef<string | null>(null)

  const navigate = useCallback(async (destination: string, history: 'push' | 'none' = 'push') => {
    const url = new URL(destination, window.location.href)
    if (url.origin !== window.location.origin || url.pathname !== new URL(initial.indexUrl, window.location.href).pathname) return
    if (request.current?.url === url.href) return
    if (url.href === committed.current && !failed.current) {
      request.current?.controller.abort()
      request.current = null
      setPending(false)
      setError('')
      return
    }
    request.current?.controller.abort()
    const current = { controller: new AbortController(), url: url.href }
    request.current = current
    setPending(true)
    setError('')
    try {
      const response = await fetch(url, { credentials: 'same-origin', signal: current.controller.signal, headers: { Accept: 'text/html' } })
      if (current.controller.signal.aborted) return
      if (response.redirected) {
        // Preserve Flask's expired-session/account-gate redirects.
        const redirected = new URL(response.url)
        if (redirected.origin === window.location.origin) window.location.assign(redirected.href)
        else throw new Error('Unexpected order destination')
        return
      }
      if (response.status === 401 || response.status === 403) { window.location.assign(url.href); return }
      if (!response.ok) throw new Error('Orders unavailable')
      const document = new DOMParser().parseFromString(await response.text(), 'text/html')
      const payload = document.getElementById('laundrix-orders-data')
      const next = parseOrdersData(JSON.parse(payload?.textContent || 'null'))
      if (current.controller.signal.aborted || request.current !== current) return
      setData(next)
      if (history === 'push' && url.href !== window.location.href) window.history.pushState(null, '', url)
      committed.current = url.href
      failed.current = null
    } catch {
      if (current.controller.signal.aborted || request.current !== current) return
      failed.current = url.href
      if (history === 'none') window.history.replaceState(null, '', committed.current)
      setError('Orders could not be loaded. Your current results are still shown. Please try again.')
    } finally {
      if (request.current === current) {
        request.current = null
        setPending(false)
      }
    }
  }, [initial.indexUrl])

  useEffect(() => {
    const pop = () => { void navigate(window.location.href, 'none') }
    window.addEventListener('popstate', pop)
    return () => { window.removeEventListener('popstate', pop); request.current?.controller.abort(); request.current = null }
  }, [navigate])

  const filterOrders = (destination: string) => {
    const target = new URL(destination, window.location.href)
    if (request.current) {
      // A status click changes only status, including while Search/Clear is in flight.
      // Do not revive the previous committed search from an older tab URL.
      const term = new URL(request.current.url).searchParams.get('q')
      if (term) target.searchParams.set('q', term)
      else target.searchParams.delete('q')
    }
    void navigate(target.href)
  }
  return { data, pending, error, navigate, filterOrders, retry: () => { if (failed.current) void navigate(failed.current) } }
}
