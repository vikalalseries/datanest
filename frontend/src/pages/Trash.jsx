import { useCallback, useEffect, useState } from 'react'

import { Confirm, Empty, useToast } from '../components/ui'
import { Spinner } from '../components/Spinner'
import * as S from '../services/sheets'
import { errorMessage } from '../services/api'

const summary = (data) => Object.entries(data).slice(0, 4).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`).join(' · ') || 'Empty row'

export default function Trash() {
  const toast = useToast()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [confirm, setConfirm] = useState(null)
  const load = useCallback(() => S.getTrash().then((d) => { setData(d); setError(null) }).catch((e) => setError(errorMessage(e))), [])
  useEffect(() => { load() }, [load])
  const run = async (fn, msg) => { try { await fn(); toast(msg); load() } catch (e) { toast(errorMessage(e), 'error') } }

  if (error) return <p role="alert" className="text-sm text-red-600">{error}</p>
  if (!data) return <Spinner />
  const empty = !data.sheets.length && !data.records.length
  return (
    <div>
      <h1 className="text-2xl font-semibold max-lg:sr-only">Trash</h1>
      <p className="mt-1 text-sm text-soft">Deleted sheets and rows stay here until you delete them permanently.</p>
      {empty && <div className="mt-6"><Empty title="Trash is empty" /></div>}
      {data.sheets.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-soft">Sheets</h2>
          <div className="space-y-2">
            {data.sheets.map((s) => (
              <div key={s.id} className="card flex flex-wrap items-center gap-3 p-4">
                <div className="min-w-0 flex-1 basis-40"><p className="truncate font-medium">{s.name}</p><p className="text-xs text-soft">{s.record_count} records</p></div>
                <button className="btn-ghost" onClick={() => run(() => S.restoreSheet(s.id), 'Sheet restored')}>Restore</button>
                <button className="btn-ghost text-red-600" onClick={() => setConfirm({ title: 'Delete permanently?', danger: true, confirmLabel: 'Delete forever', message: `“${s.name}” and all its records will be gone for good.`, onConfirm: () => run(() => S.purgeSheet(s.id), 'Deleted permanently') })}>Delete</button>
              </div>
            ))}
          </div>
        </section>
      )}
      {data.records.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-soft">Rows</h2>
          <div className="space-y-2">
            {data.records.map((r) => (
              <div key={r.id} className="card flex flex-wrap items-center gap-3 p-4">
                <div className="min-w-0 flex-1 basis-40"><p className="truncate text-sm">{summary(r.data)}</p><p className="text-xs text-soft">from {r.sheet_name}</p></div>
                <button className="btn-ghost" onClick={() => run(() => S.restoreRecords([r.id]), 'Row restored')}>Restore</button>
                <button className="btn-ghost text-red-600" aria-label="Delete row permanently" onClick={() => setConfirm({ title: 'Delete permanently?', danger: true, confirmLabel: 'Delete forever', message: 'This row will be gone for good.', onConfirm: () => run(() => S.purgeRecords([r.id]), 'Deleted permanently') })}>Delete</button>
              </div>
            ))}
          </div>
        </section>
      )}
      {confirm && <Confirm {...confirm} onClose={() => setConfirm(null)} />}
    </div>
  )
}
