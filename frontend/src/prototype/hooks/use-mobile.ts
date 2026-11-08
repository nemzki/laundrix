import { useSyncExternalStore } from 'react'

const MOBILE_QUERY = '(max-width: 767px)'
function subscribe(onChange: () => void) {
  const query = window.matchMedia(MOBILE_QUERY)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}
// Same prototype breakpoint, with a correct first client render and no effect update.
export function useIsMobile() {
  return useSyncExternalStore(subscribe, () => window.matchMedia(MOBILE_QUERY).matches, () => false)
}
