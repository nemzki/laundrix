import { Component, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { parseDashboard } from './data'
import { Dashboard } from './Dashboard'
import '@prototype/styles.css'
import './styles.css'
import './admin-polish.css'

const host = document.getElementById('laundrix-dashboard')
const payload = document.getElementById('laundrix-dashboard-data')
let root: Root | null = null
const initial = host?.cloneNode(true) as HTMLElement | undefined
function restore() {
  root?.unmount(); root = null
  if (host && initial) { host.replaceChildren(...Array.from(initial.cloneNode(true).childNodes)); host.dataset.renderer = 'server'; delete host.dataset.ready }
}
class ServerFallback extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch() { queueMicrotask(restore) }
  render() { return this.state.failed ? null : this.props.children }
}
try {
  if (host && payload) {
    const data = parseDashboard(JSON.parse(payload.textContent ?? 'null'))
    if (getComputedStyle(host).getPropertyValue('--lx-dashboard-ready').trim() !== '1') {
      location.replace(data.urls.fallback)
    } else {
      const identity = document.getElementById('dashboard-preserved-identity')
      identity?.remove()
      root = createRoot(host)
      flushSync(() => root!.render(<ServerFallback><Dashboard data={data} identity={identity}
        onReady={() => { host.dataset.renderer = 'react'; host.dataset.ready = 'true' }} /></ServerFallback>))
    }
  }
} catch { restore() }
