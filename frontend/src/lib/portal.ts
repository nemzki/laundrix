/** Radix portals share the scoped theme, outside retained legacy content. */
export function getPortalContainer(foundation = false): HTMLElement {
  const id = foundation ? 'laundrix-foundation-portals' : 'laundrix-react-portals'
  let container = document.getElementById(id)
  if (!container) {
    container = document.createElement('div')
    container.id = id
    container.className = foundation ? 'lx-react lx-foundation' : 'lx-react'
    document.body.append(container)
  }
  return container
}
