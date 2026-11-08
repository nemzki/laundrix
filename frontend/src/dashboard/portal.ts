/** Dashboard portals inherit its scoped tokens; other Phase 1 consumers keep defaults. */
export function dashboardPortal() {
  return typeof document === 'undefined' ? undefined : document.getElementById('laundrix-dashboard-portals') ?? undefined
}
