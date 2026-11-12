import { Component, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { OrdersPage } from './OrdersPage'
import { parseOrdersData } from './orders-data'

function restoreJinja() {
  const fallback = document.querySelector<HTMLElement>('[data-orders-jinja]')
  const host = document.getElementById('laundrix-react-orders')
  if (host && serverMarkup && getComputedStyle(host).getPropertyValue('--lx-react-css-ready').trim() === '1') {
    host.replaceChildren(serverMarkup.cloneNode(true))
    host.hidden = false
    host.dataset.renderer = 'server'
    delete host.dataset.ready
  } else {
    if (fallback) fallback.hidden = false
    if (host) host.hidden = true
  }
}
class JinjaFallback extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch() { restoreJinja() }
  render() { return this.state.failed ? null : this.props.children }
}
const host = document.getElementById('laundrix-react-orders')
const payload = document.getElementById('laundrix-orders-data')
const stylesheet = document.getElementById('laundrix-react-css') as HTMLLinkElement | null
const serverMarkup = document.createDocumentFragment()
if (host) Array.from(host.childNodes).forEach(node => serverMarkup.append(node.cloneNode(true)))
async function mount() {
  if (!host || !payload || !stylesheet) return
  // Deferred modules execute after the render-blocking head stylesheets. The
  // server already renders the correct listing; no timed handoff or hiding phase.
  if (getComputedStyle(host).getPropertyValue('--lx-react-css-ready').trim() !== '1') {
    throw new Error('React stylesheet unavailable')
  }
  const data = parseOrdersData(JSON.parse(payload.textContent || 'null'))
  const ready = () => {
    const fallback = document.querySelector<HTMLElement>('[data-orders-jinja]')
    if (fallback) fallback.hidden = true
    host.hidden = false
    host.dataset.ready = 'true'
    host.dataset.renderer = 'react'
  }
  createRoot(host).render(<JinjaFallback><OrdersPage data={data} onReady={ready} /></JinjaFallback>)
}
void mount().catch(restoreJinja)
