import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { Spinner } from '../components/Spinner'
import { getStats } from '../services/sheets'
import { getNotifications, getOverview } from '../services/insights'
import { errorMessage } from '../services/api'

const ACTIONS = {
  'sheet.create': 'Created sheet', 'sheet.update': 'Updated sheet', 'sheet.trash': 'Deleted sheet', 'sheet.restore': 'Restored sheet',
  'sheet.duplicate': 'Duplicated sheet', 'sheet.purge': 'Permanently deleted a sheet', 'column.add': 'Added a column to', 'column.update': 'Edited a column in',
  'column.delete': 'Removed a column from', 'record.create': 'Added a row to', 'record.update': 'Edited a row in', 'record.trash': 'Deleted rows',
  'record.restore': 'Restored rows', 'record.purge': 'Permanently deleted rows', 'record.move': 'Moved rows into',
}

export default function Dashboard() {
  const { profile, profileError } = useAuth()
  const [stats, setStats] = useState(null)
  const [statsError, setStatsError] = useState(null)
  const [overview, setOverview] = useState(null)
  const [alerts, setAlerts] = useState([])
  useEffect(() => { if (profile) getStats().then(setStats).catch((e) => setStatsError(errorMessage(e))) }, [profile])
  useEffect(() => {
    if (!profile) return
    getOverview().then((o) => setOverview(o.job)).catch(() => setOverview(null))
    getNotifications().then((n) => setAlerts(n.items.slice(0, 5))).catch(() => setAlerts([]))
  }, [profile])

  if (profileError)
    return (
      <div role="alert" className="card flex max-w-xl gap-3 p-5 text-sm">
        <AlertCircle className="h-5 w-5 shrink-0 text-red-500" />
        <div><p className="font-medium">We couldn't load your account.</p><p className="mt-1 text-soft">{profileError}</p></div>
      </div>
    )
  if (!profile) return <Spinner />
  const metrics = [['Sheets', stats?.total_sheets], ['Records', stats?.total_records]]
  if (overview) metrics.push(['Applied', overview.applications], ['Interviews', overview.interviews], ['Offers', overview.offers], ['Response rate', `${overview.response_rate}%`])

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold max-lg:sr-only">Dashboard</h1>
          <p className="mt-1 truncate text-sm text-soft">{profile.workspace.name}</p>
        </div>
        <Link to="/add" className="btn-primary">Add information</Link>
      </div>
      {statsError ? <p role="alert" className="mt-6 text-sm text-red-600">{statsError}</p> : !stats ? <div className="mt-6"><Spinner /></div> : (
        <>
          <dl aria-label="Summary" className={`mt-6 grid gap-px overflow-hidden rounded-lg border border-line bg-line ${metrics.length > 2 ? 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-6' : 'grid-cols-2'}`}>
            {metrics.map(([label, value]) => (
              <div key={label} className="bg-surface px-4 py-3"><dt className="text-xs text-soft">{label}</dt><dd className="mt-0.5 text-xl font-semibold tabular-nums">{value}</dd></div>
            ))}
          </dl>

          <div className="mt-6 grid gap-6 md:grid-cols-2">
            <section aria-label="Needs attention">
              <h2 className="font-semibold">Needs attention</h2>
              <div className="card mt-2">
                {alerts.length === 0 ? <p className="p-4 text-sm text-soft">Nothing needs attention right now.</p> : (
                  <ul className="divide-y divide-line text-sm">
                    {alerts.map((n) => (
                      <li key={n.id}><Link to={`/sheets/${n.sheet_id}`} className="flex flex-col gap-0.5 px-4 py-2.5 hover:bg-muted sm:flex-row sm:items-baseline sm:justify-between sm:gap-3"><span className="min-w-0 truncate">{n.title}</span><span className="shrink-0 text-xs text-soft">{n.sheet_name}</span></Link></li>
                    ))}
                  </ul>
                )}
              </div>
            </section>
            <section aria-label="Recent sheets">
              <h2 className="font-semibold">Recent sheets</h2>
              <div className="card mt-2">
                {stats.recent_sheets.length === 0 ? <p className="p-4 text-sm text-soft">No sheets yet. <Link className="text-brand underline" to="/sheets">Create one</Link>.</p> : (
                  <ul className="divide-y divide-line text-sm">
                    {stats.recent_sheets.map((s) => (
                      <li key={s.id}><Link to={`/sheets/${s.id}`} className="flex justify-between gap-3 px-4 py-2.5 hover:bg-muted"><span className="min-w-0 truncate">{s.name}</span><span className="shrink-0 text-soft">{s.record_count} rows</span></Link></li>
                    ))}
                  </ul>
                )}
              </div>
            </section>
          </div>

          <section aria-label="Recent activity" className="mt-6">
            <div className="flex items-center justify-between"><h2 className="font-semibold">Recent activity</h2><Link to="/activity" className="text-sm text-brand hover:underline">View all</Link></div>
            <div className="card mt-2">
              {stats.recent_activity.length === 0 ? <p className="p-4 text-sm text-soft">Nothing yet.</p> : (
                <ul className="divide-y divide-line text-sm">
                  {stats.recent_activity.map((a) => (
                    <li key={a.id} className="flex flex-col gap-0.5 px-4 py-2.5 sm:flex-row sm:justify-between sm:gap-3"><span className="min-w-0">{ACTIONS[a.action] || a.action}{a.sheet_name ? ` “${a.sheet_name}”` : ''}</span><span className="shrink-0 text-xs text-soft sm:text-sm">{new Date(a.created_at).toLocaleString()}</span></li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  )
}
