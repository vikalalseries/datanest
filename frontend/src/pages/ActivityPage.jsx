import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Undo2 } from 'lucide-react'
import { Confirm, Empty, useToast } from '../components/ui'
import { Spinner } from '../components/Spinner'
import { getActivity, undoActivity } from '../services/insights'
import { errorMessage } from '../services/api'

const LIMIT = 30

export default function ActivityPage() {
  const toast = useToast()
  const [items, setItems] = useState(null)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [confirm, setConfirm] = useState(null)

  const load = useCallback(async () => {
    try {
      const r = await getActivity({ limit: LIMIT, offset: 0 })
      setItems(r.items); setTotal(r.total); setError(null)
    } catch (e) { setError(errorMessage(e)) }
  }, [])
  useEffect(() => { load() }, [load])

  const more = async () => {
    setLoadingMore(true)
    try {
      const r = await getActivity({ limit: LIMIT, offset: items.length })
      setItems((x) => [...x, ...r.items.filter((n) => !x.some((o) => o.id === n.id))]); setTotal(r.total)
    } catch (e) { toast(errorMessage(e), 'error') } finally { setLoadingMore(false) }
  }

  const undo = async (item) => {
    try {
      const r = await undoActivity(item.id)
      toast(r.message)
      load()
    } catch (e) { toast(errorMessage(e), 'error') }
  }

  if (error) return <p role="alert" className="text-sm text-red-600">{error}</p>
  if (!items) return <Spinner />
  return (
    <div>
      <h1 className="text-2xl font-semibold max-lg:sr-only">Activity</h1>
      <p className="mt-1 text-sm text-soft">Everything that happened in your workspace, newest first. Some actions can be undone.</p>
      {items.length === 0 ? <div className="mt-6"><Empty title="No activity yet" text="Your changes will appear here." /></div> : (
        <ul className="mt-5 space-y-2">
          {items.map((a) => (
            <li key={a.id} className="card p-4">
              <div className="flex flex-wrap items-start gap-3">
                <div className="min-w-0 flex-1">
                  <p className={`text-sm font-medium ${a.undone ? 'text-soft line-through' : ''}`}>
                    {a.sheet_id && a.sheet_name ? <Link to={`/sheets/${a.sheet_id}`} className="hover:underline">{a.summary}</Link> : a.summary}
                  </p>
                  <p className="text-xs text-soft">{new Date(a.created_at).toLocaleString()}{a.undone ? ' · undone' : ''}</p>
                  {a.changes.length > 0 && (
                    <ul className="mt-2 space-y-0.5 text-xs">
                      {a.changes.map((c, i) => <li key={i}><span className="text-soft">{c.column}:</span> <span className="line-through opacity-70">{c.before}</span> → <span className="font-medium">{c.after}</span></li>)}
                    </ul>
                  )}
                </div>
                {a.undoable && (
                  <button className="btn-ghost" onClick={() => setConfirm({ title: 'Undo this action?', confirmLabel: 'Undo', message: `${a.summary}. If something changed since, the undo is refused so newer edits are never overwritten.`, onConfirm: () => undo(a) })}>
                    <Undo2 className="h-4 w-4" />Undo
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {items.length < total && <button className="btn-ghost mt-4" onClick={more} disabled={loadingMore}>{loadingMore ? 'Loading…' : `Show more (${total - items.length} older)`}</button>}
      {confirm && <Confirm {...confirm} onClose={() => setConfirm(null)} />}
    </div>
  )
}
