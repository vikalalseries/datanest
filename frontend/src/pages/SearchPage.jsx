import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Search as SearchIcon, Table2 } from 'lucide-react'
import { Empty, inputCls, useDebounced } from '../components/ui'
import { Spinner } from '../components/Spinner'
import { categoryLabel, searchAll, searchFacets } from '../services/insights'
import { errorMessage } from '../services/api'

const LIMIT = 30
const show = (v) => (Array.isArray(v) ? v.join(', ') : String(v))

export default function SearchPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const category = params.get('category') || ''
  const status = params.get('status') || ''
  const from = params.get('from') || ''
  const to = params.get('to') || ''
  const [text, setText] = useState(q)
  const [facets, setFacets] = useState({ categories: [], statuses: [] })
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [offset, setOffset] = useState(0)
  const debounced = useDebounced(text, 350)

  const set = (patch) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) (v ? next.set(k, v) : next.delete(k))
    setParams(next, { replace: true })
    setOffset(0)
  }

  useEffect(() => { searchFacets().then(setFacets).catch(() => {}) }, [])
  useEffect(() => { setText(q) }, [q])
  useEffect(() => { if (debounced !== q) set({ q: debounced }) }, [debounced]) // eslint-disable-line react-hooks/exhaustive-deps

  const hasQuery = Boolean(q || category || status || from || to)
  useEffect(() => {
    if (!hasQuery) { setData(null); setError(null); return }
    let cancelled = false
    searchAll({ q: q || undefined, category: category || undefined, status: status || undefined, date_from: from || undefined, date_to: to || undefined, limit: LIMIT, offset })
      .then((r) => { if (!cancelled) { setData(r); setError(null) } })
      .catch((e) => { if (!cancelled) { setError(errorMessage(e)); setData(null) } })
    return () => { cancelled = true }
  }, [q, category, status, from, to, offset, hasQuery])

  return (
    <div>
      <h1 className="text-2xl font-semibold max-lg:sr-only">Search</h1>
      <div className="relative mt-4">
        <SearchIcon className="absolute left-3 top-2.5 h-4 w-4 text-soft" />
        <input autoFocus className={`${inputCls} pl-9`} placeholder="Search sheets, companies, or any value" aria-label="Search query" value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="text-xs font-medium text-soft">Category
          <select className={`${inputCls} mt-1`} value={category} onChange={(e) => set({ category: e.target.value })}>
            <option value="">All categories</option>
            {facets.categories.map((c) => <option key={c.value} value={c.value}>{categoryLabel(c.value)} ({c.count})</option>)}
          </select>
        </label>
        <label className="text-xs font-medium text-soft">Status
          <select className={`${inputCls} mt-1`} value={status} onChange={(e) => set({ status: e.target.value })}>
            <option value="">Any status</option>
            {facets.statuses.map((s) => <option key={s.value} value={s.value}>{s.value} ({s.count})</option>)}
          </select>
        </label>
        <label className="text-xs font-medium text-soft">Date from<input type="date" className={`${inputCls} mt-1`} value={from} max={to || undefined} onChange={(e) => set({ from: e.target.value })} /></label>
        <label className="text-xs font-medium text-soft">Date to<input type="date" className={`${inputCls} mt-1`} value={to} min={from || undefined} onChange={(e) => set({ to: e.target.value })} /></label>
      </div>
      {(category || status || from || to) && <button className="mt-2 text-sm text-brand underline" onClick={() => set({ category: '', status: '', from: '', to: '' })}>Clear filters</button>}

      <div className="mt-6">
        {!hasQuery ? <Empty icon={SearchIcon} title="Search all your sheets" text="Type a word, or pick a category, status or date range." /> : error ? <p role="alert" className="text-sm text-red-600">{error}</p> : !data ? <Spinner /> : (
          <>
            {data.sheets.length > 0 && (
              <section aria-label="Matching sheets">
                <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-soft">Sheets</h2>
                <div className="grid gap-2 sm:grid-cols-2">
                  {data.sheets.map((s) => <Link key={s.id} to={`/sheets/${s.id}`} className="card flex items-center gap-3 p-3 hover:border-brand/50"><Table2 className="h-4 w-4 text-brand" /><span className="min-w-0 flex-1 truncate font-medium">{s.name}</span><span className="text-xs text-soft">{s.record_count} rows</span></Link>)}
                </div>
              </section>
            )}
            <section aria-label="Matching records" className="mt-6">
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-soft">Records ({data.total})</h2>
              {data.records.length === 0 ? <Empty icon={SearchIcon} title="No records match" text="Try fewer words or clear a filter." /> : (
                <div className="space-y-2">
                  {data.records.map((r) => (
                    <Link key={r.id} to={`/sheets/${r.sheet_id}`} className="card block p-4 hover:border-brand/50">
                      <p className="text-xs font-medium text-brand">{r.sheet_name} · {categoryLabel(r.category)}</p>
                      <dl className="mt-1 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
                        {Object.entries(r.data).slice(0, 6).map(([k, v]) => <div key={k} className="flex gap-2"><dt className="shrink-0 text-soft">{k}:</dt><dd className="truncate">{show(v)}</dd></div>)}
                      </dl>
                    </Link>
                  ))}
                  <div className="flex items-center justify-between pt-2 text-sm text-soft">
                    <span>{data.total === 0 ? 0 : offset + 1}–{Math.min(offset + LIMIT, data.total)} of {data.total}</span>
                    <div className="flex gap-1">
                      <button className="btn-ghost !px-2" aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}><ChevronLeft className="h-4 w-4" /></button>
                      <button className="btn-ghost !px-2" aria-label="Next page" disabled={offset + LIMIT >= data.total} onClick={() => setOffset(offset + LIMIT)}><ChevronRight className="h-4 w-4" /></button>
                    </div>
                  </div>
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  )
}
