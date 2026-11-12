import { useLayoutEffect } from 'react'

// react-remove-scroll-bar normally injects a <style> element, which Flask's
// existing CSP rejects. Keep Radix's scroll/focus handling and replace only that
// stylesheet injector with equivalent DOM style-property updates (CSP compliant).
export const zeroRightClassName = 'right-scroll-bar-position'
export const fullWidthClassName = 'width-before-scroll-bar'
export const noScrollbarsClassName = 'with-scroll-bars-hidden'
export const removedBarSizeVariable = '--removed-body-scroll-bar-size'

let locks = 0
let restore: (() => void) | undefined
// Non-component exports implement the upstream module's public interface.
// oxlint-disable-next-line react/only-export-components
export function getGapWidth() {
  return { left: 0, top: 0, right: 0, gap: Math.max(0, window.innerWidth - document.documentElement.clientWidth) }
}
export function RemoveScrollBar() {
  useLayoutEffect(() => {
    const body = document.body
    if (locks === 0) {
      const names = ['overflow', 'overscroll-behavior', 'padding-right', removedBarSizeVariable]
      const previous = names.map(name => [name, body.style.getPropertyValue(name), body.style.getPropertyPriority(name)])
      const originalAttribute = body.getAttribute('data-scroll-locked')
      const { gap } = getGapWidth()
      const padding = Number.parseFloat(getComputedStyle(body).paddingRight) || 0
      body.style.setProperty('overflow', 'hidden', 'important')
      body.style.setProperty('overscroll-behavior', 'contain')
      body.style.setProperty('padding-right', `${padding + gap}px`)
      body.style.setProperty(removedBarSizeVariable, `${gap}px`)
      restore = () => {
        previous.forEach(([name, value, priority]) => {
          if (value) body.style.setProperty(name, value, priority)
          else body.style.removeProperty(name)
        })
        if (originalAttribute === null) body.removeAttribute('data-scroll-locked')
        else body.setAttribute('data-scroll-locked', originalAttribute)
      }
    }
    locks++
    body.setAttribute('data-scroll-locked', String(locks))
    return () => {
      locks--
      if (locks === 0) { restore?.(); restore = undefined }
      else body.setAttribute('data-scroll-locked', String(locks))
    }
  }, [])
  return null
}
