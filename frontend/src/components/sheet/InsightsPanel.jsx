import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { getSheetAnalytics } from '../../services/insights'

const fmt = (m) => {
  const v = typeof m.value === 'number' ? m.value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : m.value
  return m.unit ? `${v}${m.unit}` : v
}

/** Shows category-specific insights. Renders NOTHING for sheets whose category has no meaningful analytics. */
export default function InsightsPanel({ sheetId, refreshKey }) {
  const [data, setData] = useState(null)
  const [open, setOpen] = useState(true)

  useEffect(() => {
    let cancelled = false
    getSheetAnalytics(sheetId).then((d) => !cancelled && setData(d)).catch(() => !cancelled && setData(null))
    return () => { cancelled = true }
  }, [sheetId, refreshKey])

  if (!data || !data.applicable) return null
  const max = Math.max(1, ...data.breakdown.map((b) => b.value))
  return (
    <section className="card mt-4 p-4" aria-label="Insights">
      <button className="flex w-full items-center justify-between text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="font-semibold">{data.kind === 'job' ? 'Application insights' : 'Spending insights'}</span>
        {open ? <ChevronUp className="h-4 w-4 text-soft" /> : <ChevronDown className="h-4 w-4 text-soft" />}
      </button>
      {open && (
        <>
          <dl className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line sm:grid-cols-3 lg:grid-cols-6">
            {data.metrics.map((m) => (
              <div key={m.key} className="bg-surface px-3 py-2" title={m.hint}>
                <dt className="text-xs text-soft">{m.label}</dt>
                <dd className="text-xl font-semibold tabular-nums">{fmt(m)}</dd>
              </div>
            ))}
          </dl>
          {data.breakdown.length > 0 && (
            <div className="mt-4">
              <p className="text-xs font-medium text-soft">{data.kind === 'job' ? 'By status' : 'By category'}</p>
              <ul className="mt-2 space-y-1.5">
                {data.breakdown.map((b) => (
                  <li key={b.label} className="flex items-center gap-3 text-sm">
                    <span className="w-24 shrink-0 truncate sm:w-32" title={b.label}>{b.label}</span>
                    <span className="h-1.5 flex-1 overflow-hidden rounded-sm bg-muted" aria-hidden="true"><span className="block h-full rounded-sm bg-brand" style={{ width: `${(b.value / max) * 100}%` }} /></span>
                    <span className="w-16 text-right tabular-nums">{b.value.toLocaleString()}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.notes.map((n) => <p key={n} className="mt-3 text-xs text-soft">{n}</p>)}
        </>
      )}
    </section>
  )
}
