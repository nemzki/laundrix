import { Component, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { getPortalContainer } from '@/lib/portal'
import { Staff } from './Staff'
import { parseList } from './api'
import '../index.css'
import './styles.css'
const host=document.getElementById('laundrix-staff')
class StartupBoundary extends Component<{children:ReactNode},{failed:boolean}>{state={failed:false};static getDerivedStateFromError(){return {failed:true}}render(){return this.state.failed?<div role="alert" className="staff-startup-error"><strong>Staff Management could not load.</strong><p>Reload the page to try again.</p><button type="button" onClick={()=>location.reload()}>Reload Staff Management</button></div>:this.props.children}}
function showStartupError(){if(!host)return;host.replaceChildren();host.dataset.ready='error';const panel=document.createElement('div');panel.className='staff-startup-error';panel.setAttribute('role','alert');const title=document.createElement('strong');title.textContent='Staff Management could not load.';const description=document.createElement('p');description.textContent='Reload the page to try again.';const retry=document.createElement('button');retry.type='button';retry.textContent='Reload Staff Management';retry.addEventListener('click',()=>location.reload());panel.append(title,description,retry);host.append(panel)}
try{
 if(!host||getComputedStyle(host).getPropertyValue('--staff-ready').trim()!=='1')throw new Error('Staff Management styles are unavailable.')
 getPortalContainer().classList.add('lx-staff')
 const initial=parseList(document)
 flushSync(()=>createRoot(host).render(<StartupBoundary><Staff initial={initial}/></StartupBoundary>))
 host.dataset.ready='true'
}catch{showStartupError()}
