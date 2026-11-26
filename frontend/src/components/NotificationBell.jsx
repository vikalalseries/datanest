import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlarmClock, Bell, CalendarClock, Hourglass, PartyPopper } from 'lucide-react'
import { getNotifications } from '../services/insights'

const KEY = 'datanest-dismissed-notifications'
const ICON = { overdue: AlarmClock, due_soon: CalendarClock, no_response: Hourglass, welcome: PartyPopper }
const TONE = { danger: 'text-red-600', warning: 'text-amber-600', info: 'text-soft' }

// Shown to every user until they dismiss it. The id includes the user, so a second account on the same device gets its own.
const welcomeFor = (userId) => ({
  id: `welcome:${userId}`, kind: 'welcome', severity: 'info', to: '/about',
  title: 'Welcome to DataNest!', detail: 'See what you can do here and how to get started.',
})

function loadDismissed() {
  try { return new Set(JSON.parse(localStorage.getItem(KEY) || '[]')) } catch { return new Set() }
}
function saveDismissed(set) {
  try { localStorage.setItem(KEY, JSON.stringify([...set].slice(-300))) } catch { /* per-device convenience only */ }
}

/** A welcome message, then computed alerts: deadlines, overdue items, applications with no reply. Dismissals are remembered on this device. */
export default function NotificationBell({ userId, refreshMs = 5 * 60 * 1000 }) {
  const [items, setItems] = useState([])
  const [open, setOpen] = useState(false)
  const [dismissed, setDismissed] = useState(loadDismissed)
  const [failed, setFailed] = useState(false)
  const ref = useRef(null)

  const load = useCallback(() => getNotifications().then((r) => { setItems(r.items); setFailed(false) }).catch(() => setFailed(true)), [])
  useEffect(() => {
    load()
    const t = setInterval(load, refreshMs)
    return () => clearInterval(t)
  }, [load, refreshMs])
  useEffect(() => {
    if (!open) return
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey) }
  }, [open])

  const all = userId ? [...items, welcomeFor(userId)] : items
  const visible = all.filter((i) => !dismissed.has(i.id))
  const dismiss = (ids) => setDismissed((d) => { const n = new Set(d); ids.forEach((i) => n.add(i)); saveDismissed(n); return n })

  return (
    <div className="relative" ref={ref}>
      <button className="btn-ghost relative" onClick={() => { setOpen((o) => !o); if (!open) load() }} aria-label={`Notifications${visible.length ? `, ${visible.length} new` : ''}`} aria-expanded={open} aria-haspopup="true">
        <Bell className="h-4 w-4" />
        {visible.length > 0 && <span className="absolute -right-1 -top-1 grid h-4 min-w-[1rem] place-items-center rounded-full bg-red-600 px-1 text-[10px] font-semibold text-white">{visible.length > 9 ? '9+' : visible.length}</span>}
      </button>
      {open && (
        <div role="region" aria-label="Notifications" className="card absolute right-0 z-30 mt-2 w-[min(24rem,92vw)] p-2">
          <div className="flex items-center justify-between px-2 py-1">
            <p className="text-sm font-semibold">Notifications</p>
            {visible.length > 0 && <button className="text-xs text-brand underline" onClick={() => dismiss(visible.map((i) => i.id))}>Dismiss all</button>}
          </div>
          {failed && <p className="px-2 py-2 text-sm text-soft">Couldn't check for updates right now.</p>}
          {!failed && visible.length === 0 && <p className="px-2 py-4 text-sm text-soft">You're all caught up. Deadlines and applications waiting for a reply will show up here.</p>}
          <ul className="max-h-96 overflow-auto">
            {visible.map((n) => {
              const Icon = ICON[n.kind] || Bell
              return (
                <li key={n.id} className="flex items-start gap-2 rounded-lg px-2 py-2 hover:bg-muted">
                  <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${TONE[n.severity] || ''}`} />
                  <Link to={n.to || `/sheets/${n.sheet_id}`} className="min-w-0 flex-1" onClick={() => setOpen(false)}>
                    <span className="block truncate text-sm">{n.title}</span>
                    <span className={`block text-xs text-soft ${n.kind === 'welcome' ? '' : 'truncate'}`}>{n.detail}</span>
                  </Link>
                  <button className="text-xs text-soft hover:text-ink" aria-label={`Dismiss: ${n.title}`} onClick={() => dismiss([n.id])}>✕</button>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
