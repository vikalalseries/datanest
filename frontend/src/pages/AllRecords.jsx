import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Search } from 'lucide-react'
import { Empty, inputCls, useDebounced } from '../components/ui'
import { Spinner } from '../components/Spinner'
import { allRecords } from '../services/sheets'
import { errorMessage } from '../services/api'

const LIMIT = 50

export default function AllRecords() {
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => setOffset(0), [dq])
  useEffect(() => {
    allRecords({ q: dq || undefined, limit: LIMIT, offset }).then((p) => { setPage(p); setError(null) }).catch((e) => setError(errorMessage(e)))
  }, [dq, offset])

  return (
    <div>
      <h1 className="text-2xl font-semibold max-lg:sr-only">All records</h1>
      <div className="relative mt-5 max-w-sm">
        <Search className="absolute left-3 top-2.5 h-4 w-4 text-soft" />
        <input className={`${inputCls} pl-9`} placeholder="Search every sheet" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search all records" />
      </div>
      <div className="mt-5">
        {error ? <p role="alert" className="text-sm text-red-600">{error}</p> : !page ? <Spinner /> : page.items.length === 0 ? (
          <Empty title={dq ? 'Nothing matches your search' : 'No records yet'} text={dq ? undefined : 'Records you add to any sheet appear here.'} />
        ) : (
          <div className="space-y-2">
            {page.items.map((r) => (
              <div key={r.id} className="card p-4">
                <Link to={`/sheets/${r.sheet_id}`} className="text-xs font-medium text-brand hover:underline">{r.sheet_name}</Link>
                <dl className="mt-1 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
                  {Object.entries(r.data).slice(0, 6).map(([k, v]) => (
                    <div key={k} className="flex gap-2"><dt className="shrink-0 text-soft">{k}:</dt><dd className="truncate">{Array.isArray(v) ? v.join(', ') : String(v)}</dd></div>
                  ))}
                  {Object.keys(r.data).length === 0 && <dd className="text-soft">Empty row</dd>}
                </dl>
              </div>
            ))}
            <div className="flex items-center justify-between pt-2 text-sm text-soft">
              <span>{offset + 1}–{Math.min(offset + LIMIT, page.total)} of {page.total}</span>
              <div className="flex gap-1">
                <button className="btn-ghost !px-2" aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}><ChevronLeft className="h-4 w-4" /></button>
                <button className="btn-ghost !px-2" aria-label="Next page" disabled={offset + LIMIT >= page.total} onClick={() => setOffset(offset + LIMIT)}><ChevronRight className="h-4 w-4" /></button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
