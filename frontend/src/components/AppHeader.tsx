import { NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/auth'

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Overview' },
  { to: '/campaigns', label: 'Campaigns' },
  { to: '/prospects', label: 'Prospects' },
  { to: '/outreach', label: 'Outreach' },
  { to: '/history', label: 'Reports' },
  { to: '/settings', label: 'Settings' },
]

export function AppHeader() {
  const { signOut } = useAuth()
  const { pathname } = useLocation()

  function isCurrentSection(to: string) {
    if (to === '/campaigns') return pathname === '/campaigns' || pathname === '/discover'
    if (to === '/prospects') return pathname === '/prospects' || /^\/campaigns\/[^/]+\/prospects\/[^/]+$/.test(pathname)
    if (to === '/history') return pathname === '/history' || pathname === '/research' || pathname.startsWith('/research/') || pathname.startsWith('/reports/')
    return pathname === to
  }

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-canvas/95 backdrop-blur-sm">
      <div className="mx-auto flex h-16 max-w-[1320px] items-center justify-between gap-6 px-5 sm:px-8">
        <NavLink to="/dashboard" className="flex items-center">
          <span className="font-display text-[22px] font-bold tracking-[-0.04em] text-brand">
            OpportunityCue
          </span>
        </NavLink>
        <div className="flex min-w-0 items-center gap-3 sm:gap-5">
          <nav aria-label="Primary" className="flex min-w-0 items-center gap-1 self-stretch overflow-x-auto">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end
                aria-current={isCurrentSection(item.to) ? 'page' : undefined}
                className={() =>
                  'flex h-16 shrink-0 items-center border-b-2 px-1.5 font-ui text-[13px] transition-colors sm:px-2.5 ' +
                  (isCurrentSection(item.to)
                    ? 'border-action font-semibold text-action'
                    : 'border-transparent text-ink-faint hover:text-ink')
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <button
            type="button"
            onClick={() => void signOut()}
            className="h-8 rounded-control px-2.5 font-ui text-[12px] font-medium text-ink-faint transition-colors hover:bg-panel hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  )
}
