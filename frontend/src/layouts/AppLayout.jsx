import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Bot, ChevronRight, CirclePlus, House, Menu, MoreHorizontal, Search, Table2, X } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../hooks/useTheme'
import NotificationBell from '../components/NotificationBell'
import { PageTitleContext } from './PageTitle'

const ITEMS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/sheets', label: 'Sheets' },
  { to: '/records', label: 'All records' },
  { to: '/activity', label: 'Activity' },
  { to: '/assistant', label: 'Assistant' },
  { to: '/templates', label: 'Templates' },
  { to: '/import', label: 'Import' },
]
const FOOTER = [
  { to: '/trash', label: 'Trash' },
  { to: '/settings', label: 'Settings' },
]
const TABS = [
  { to: '/dashboard', label: 'Home', icon: House },
  { to: '/sheets', label: 'Sheets', icon: Table2 },
  { to: '/add', label: 'Add', icon: CirclePlus },
  { to: '/assistant', label: 'Assistant', icon: Bot },
]
const TITLES = {
  '/dashboard': 'Dashboard', '/sheets': 'Sheets', '/records': 'All records', '/activity': 'Activity', '/assistant': 'Assistant',
  '/templates': 'Templates', '/import': 'Import', '/add': 'Add information', '/search': 'Search', '/trash': 'Trash',
  '/settings': 'Settings', '/profile': 'Profile',
}

const linkCls = ({ isActive }) =>
  `flex items-center justify-between rounded-md px-3 py-2.5 text-base transition ${isActive ? 'bg-muted font-medium text-ink' : 'text-soft hover:bg-muted hover:text-ink'}`

function SideLink({ to, label }) {
  return (
    <NavLink to={to} className={linkCls}>
      {({ isActive }) => (
        <>
          <span>{label}</span>
          {isActive && <ChevronRight className="h-4 w-4 shrink-0" aria-hidden="true" />}
        </>
      )}
    </NavLink>
  )
}

function AccountMenu({ name, avatar, onNavigate }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const { signOut } = useAuth()
  const { dark, toggle } = useTheme()

  useEffect(() => {
    if (!open) return
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey) }
  }, [open])

  const item = 'block w-full rounded-md px-3 py-2.5 text-left text-base hover:bg-muted'
  return (
    <div className="relative" ref={ref}>
      {open && (
        <div role="menu" aria-label="Account" className="card absolute bottom-full left-0 right-0 mb-2 p-1">
          <Link role="menuitem" to="/profile" className={item} onClick={() => { setOpen(false); onNavigate() }}>Profile</Link>
          <button role="menuitem" className={`${item} flex items-center justify-between`} onClick={toggle}>
            <span>Dark theme</span><span className="text-xs text-soft">{dark ? 'On' : 'Off'}</span>
          </button>
          <button role="menuitem" className={item} onClick={signOut}>Sign out</button>
        </div>
      )}
      <button
        className="flex w-full items-center gap-3 rounded-md border border-line p-2 text-left hover:bg-muted"
        onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open} aria-label="Account menu"
      >
        {avatar ? (
          <img src={avatar} alt="" referrerPolicy="no-referrer" className="h-8 w-8 rounded-full" />
        ) : (
          <span className="grid h-8 w-8 place-items-center rounded-full bg-muted text-xs font-semibold">{(name || '?')[0].toUpperCase()}</span>
        )}
        <span className="min-w-0 flex-1 truncate text-base">{name}</span>
      </button>
    </div>
  )
}

export function AppLayout() {
  const [open, setOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [pageTitle, setPageTitleState] = useState(null)
  const setPageTitle = useCallback((t) => setPageTitleState(t), [])
  const { profile, session } = useAuth()
  const nav = useNavigate()
  const location = useLocation()
  const [q, setQ] = useState('')
  const close = () => setOpen(false)
  const path = location.pathname

  useEffect(() => { setOpen(false); setSearchOpen(false) }, [path])
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  const submitSearch = (e) => {
    e.preventDefault()
    const t = q.trim()
    nav(t ? `/search?q=${encodeURIComponent(t)}` : '/search')
    close()
  }
  const meta = session?.user?.user_metadata || {}
  const name = profile?.full_name || meta.full_name || meta.name || session?.user?.email
  const avatar = profile?.avatar_url || meta.avatar_url || meta.picture
  const title = pageTitle || TITLES[path] || (path.startsWith('/sheets/') ? 'Sheet' : 'DataNest')
  const showFab = path === '/dashboard' || path.startsWith('/sheets')

  const tabCls = ({ isActive }) =>
    `flex flex-1 flex-col items-center justify-center gap-0.5 border-t-2 text-[11px] ${isActive ? 'border-ink font-semibold text-ink' : 'border-transparent text-soft'}`

  return (
    <PageTitleContext.Provider value={setPageTitle}>
      <div className="min-h-screen lg:flex">
        {open && <div className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={close} />}
        <aside
          aria-label="Main navigation"
          className={`fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col border-r border-line bg-surface p-4 pt-[max(1rem,env(safe-area-inset-top))] transition-transform lg:sticky lg:top-0 lg:z-auto lg:h-screen lg:w-60 lg:max-w-none lg:shrink-0 lg:translate-x-0 lg:pt-4 ${
            open ? 'translate-x-0' : '-translate-x-full'
          }`}
        >
          <div className="mb-4 flex shrink-0 items-center justify-between px-1">
            <span className="text-2xl font-bold tracking-tight">DataNest</span>
            <button className="grid h-11 w-11 place-items-center rounded-md hover:bg-muted lg:hidden" onClick={close} aria-label="Close menu"><X className="h-5 w-5" /></button>
          </div>
          {/* Only this middle part scrolls on short screens, so the site name and account button stay visible */}
          <div className="mb-3 flex min-h-0 flex-1 flex-col overflow-y-auto">
            <Link to="/add" className="btn-primary w-full shrink-0 !py-2.5 !text-base" onClick={close}>
              Add information
              {path === '/add' && <ChevronRight className="h-4 w-4 shrink-0" aria-hidden="true" />}
            </Link>
            <nav className="mt-3 flex-1" aria-label="Pages">
              <ul className="space-y-1">
                {ITEMS.map((item) => <li key={item.to}><SideLink {...item} /></li>)}
              </ul>
            </nav>
            <ul className="mt-4 space-y-1 border-t border-line pt-3">
              {FOOTER.map((item) => <li key={item.to}><SideLink {...item} /></li>)}
            </ul>
          </div>
          <AccountMenu name={name} avatar={avatar} onNavigate={close} />
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex flex-wrap items-center gap-2 border-b border-line bg-surface px-4 py-2.5 lg:gap-3 lg:py-3">
            <button className="btn-ghost !h-11 !w-11 !px-0 lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
            <p className="min-w-0 flex-1 truncate text-lg font-semibold lg:hidden" aria-hidden="true">{title}</p>
            <form role="search" onSubmit={submitSearch} className={`${searchOpen ? 'block' : 'hidden'} min-w-0 max-lg:order-last max-lg:basis-full lg:block lg:max-w-md lg:flex-1`}>
              <input aria-label="Search everything" className="w-full rounded-md border border-line bg-bg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand" placeholder="Search all sheets" value={q} onChange={(e) => setQ(e.target.value)} maxLength={200} autoFocus={searchOpen} />
            </form>
            <div className="flex items-center gap-2 lg:ml-auto">
              <button className="btn-ghost !h-11 !w-11 !px-0 lg:hidden" onClick={() => setSearchOpen((s) => !s)} aria-label="Search" aria-expanded={searchOpen}><Search className="h-5 w-5" /></button>
              <NotificationBell />
            </div>
          </header>
          <main className="min-w-0 flex-1 p-4 pb-28 sm:p-6 sm:pb-28 lg:p-8"><Outlet /></main>
        </div>

        {showFab && (
          <Link to="/add" className="btn-primary fixed bottom-[calc(5rem+env(safe-area-inset-bottom))] right-4 z-20 !h-12 !rounded-full !px-5 shadow-lg lg:hidden">+ Add data</Link>
        )}
        <nav aria-label="Primary" className="fixed inset-x-0 bottom-0 z-30 flex h-16 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] box-content lg:hidden">
          {TABS.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} className={tabCls}><Icon className="h-5 w-5" aria-hidden="true" />{label}</NavLink>)}
          <button className="flex flex-1 flex-col items-center justify-center gap-0.5 border-t-2 border-transparent text-[11px] text-soft" onClick={() => setOpen(true)}><MoreHorizontal className="h-5 w-5" aria-hidden="true" />More</button>
        </nav>
      </div>
    </PageTitleContext.Provider>
  )
}
