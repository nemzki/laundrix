import { createContext, useContext, type ReactNode } from 'react'
const PortalTheme = createContext(false)
export function FoundationPortalTheme({ children }: { children: ReactNode }) {
  return <PortalTheme.Provider value={true}>{children}</PortalTheme.Provider>
}
// A hook shared by the existing shadcn portal wrappers; legacy is the default.
// oxlint-disable-next-line react/only-export-components
export function useFoundationPortalTheme() { return useContext(PortalTheme) }
