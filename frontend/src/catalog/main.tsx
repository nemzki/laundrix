import { Component, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { getPortalContainer } from '@/lib/portal'
import { Catalog } from './Catalog'
import { parseCatalog } from './api'
import '../index.css'
import './styles.css'

const host=document.getElementById('laundrix-catalog')
function activate() {
  if(host){host.dataset.renderer='react';host.dataset.ready='true'}
  for(const [id,placeholder] of [['catalog-action-react','.catalog-boot-action'],['catalog-summary-react','.catalog-boot-summary']]) {
    const target=document.getElementById(id)
    target?.querySelector(placeholder)?.remove()
  }
}
function showStartupError() {
  if(!host)return
  host.replaceChildren();host.dataset.ready='error'
  const panel=document.createElement('div');panel.className='catalog-startup-error';panel.setAttribute('role','alert')
  const title=document.createElement('strong');title.textContent='Services & Pricing could not load.'
  const description=document.createElement('p');description.textContent='Reload the page to try again.'
  const retry=document.createElement('button');retry.type='button';retry.textContent='Reload Services & Pricing';retry.addEventListener('click',()=>location.reload())
  panel.append(title,description,retry);host.append(panel)
}
class StartupBoundary extends Component<{children:ReactNode},{failed:boolean}> {
  state={failed:false}
  static getDerivedStateFromError(){return {failed:true}}
  render(){return this.state.failed?<div role="alert" className="catalog-startup-error"><strong>Services & Pricing could not load.</strong><p>Reload the page to try again.</p><button type="button" onClick={()=>location.reload()}>Reload Services & Pricing</button></div>:this.props.children}
}
try {
  if(!host||getComputedStyle(host).getPropertyValue('--catalog-ready').trim()!=='1')throw new Error('Catalog stylesheet unavailable')
  getPortalContainer().classList.add('lx-catalog')
  const data=parseCatalog(document)
  flushSync(()=>createRoot(host).render(<StartupBoundary><Catalog initial={data} onReady={activate}/></StartupBoundary>))
} catch {showStartupError()}
