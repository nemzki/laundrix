import { useSyncExternalStore } from 'react'

function subscribe(listener: () => void) {
  window.addEventListener('laundrix:themechange', listener)
  return () => window.removeEventListener('laundrix:themechange', listener)
}
function snapshot(): 'light' | 'dark' {
  return document.documentElement.dataset.lxTheme === 'dark' ? 'dark' : 'light'
}
export function useResolvedTheme() {
  return useSyncExternalStore(subscribe, snapshot, () => 'light' as const)
}
