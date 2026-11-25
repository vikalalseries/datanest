import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, CheckCircle2, Info, Loader2, Search } from 'lucide-react'
import { inputCls, useDebounced } from '../ui'
import { errorMessage } from '../../services/api'
import { bulkAdd, checkDuplicates, matchColumns, rankSheets } from '../../services/ai'

const hasValue = (v) => !(v === undefined || v === null || v === '' || (Array.isArray(v) && !v.length))
const BADGE = { exact: 'exact name', synonym: 'similar name', fuzzy: 'similar name', ai: 'AI match' }

/**
 * Choose an existing sheet, review how extracted fields map to its columns, resolve duplicates, save.
 * `extraction` is the current (edited) preview as {category, columns:[{name,type}], records:[{values}]}.
 */
export default function ExistingSheetPanel({ extraction, source, onSaved, onChooseNew, initialSheetId, actionSlot }) {
  const [ranked, setRanked] = useState(null)
  const [q, setQ] = useState('')
  const [sheetId, setSheetId] = useState(initialSheetId || null)
  const [match, setMatch] = useState(null)
  const [matching, setMatching] = useState(false)
  const [mapping, setMapping] = useState({})
  const [dups, setDups] = useState(null)
  const [keepRows, setKeepRows] = useState({}) // row index -> true when the user chose "add anyway"
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const withData = useMemo(
    () => new Set(extraction.columns.filter((c) => extraction.records.some((r) => hasValue(r.values[c.name]))).map((c) => c.name)),
    [extraction],
  )

  useEffect(() => {
    rankSheets(extraction).then(setRanked).catch((e) => { setRanked([]); setError(errorMessage(e)) })
    // ranking is computed once for the extraction as first shown
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!sheetId) return
    let cancelled = false
    setMatching(true); setMatch(null); setDups(null); setError(null)
    matchColumns(sheetId, extraction, true)
      .then((m) => {
        if (cancelled) return
        setMatch(m)
        const init = {}
        for (const c of extraction.columns) {
          const mp = m.mappings.find((x) => x.extracted === c.name)
          if (mp?.sheet_column_id) init[c.name] = { action: 'map', column_id: mp.sheet_column_id }
          else init[c.name] = withData.has(c.name) ? { action: 'create', type: c.type } : { action: 'skip' }
        }
        setMapping(init)
      })
      .catch((e) => !cancelled && setError(errorMessage(e)))
      .finally(() => !cancelled && setMatching(false))
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sheetId])

  const dmapping = useDebounced(mapping, 500)
  useEffect(() => {
    if (!sheetId || !match) return
    let cancelled = false
    checkDuplicates(sheetId, { columns: extraction.columns, mapping: dmapping, records: extraction.records })
      .then((d) => { if (!cancelled) { setDups(d); setKeepRows({}) } })
      .catch(() => !cancelled && setDups({ duplicates: [], within_batch: [] }))
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dmapping, match])

  const dupRows = useMemo(() => {
    const m = new Map()
    dups?.duplicates.forEach((d) => m.set(d.row, { kind: 'existing', d }))
    dups?.within_batch.forEach((d) => !m.has(d.row) && m.set(d.row, { kind: 'batch', d }))
    return m
  }, [dups])
  const skipped = (i) => dupRows.has(i) && !keepRows[i]
  const rowsToAdd = extraction.records.filter((_, i) => !skipped(i))

  const sheetCols = match?.sheet.columns || []
  const usedBy = (colId) => Object.entries(mapping).find(([, a]) => a.action === 'map' && a.column_id === colId)?.[0]
  const setAction = (name, value) => {
    if (value === '__create') setMapping((m) => ({ ...m, [name]: { action: 'create', type: extraction.columns.find((c) => c.name === name).type } }))
    else if (value === '__skip') setMapping((m) => ({ ...m, [name]: { action: 'skip' } }))
    else setMapping((m) => ({ ...m, [name]: { action: 'map', column_id: value } }))
  }
  const selectValue = (name) => {
    const a = mapping[name]
    return !a ? '__skip' : a.action === 'map' ? a.column_id : a.action === 'create' ? '__create' : '__skip'
  }
  const skippedWithData = [...withData].filter((n) => mapping[n]?.action === 'skip')
  const nameClash = Object.entries(mapping).find(([n, a]) => a.action === 'create' && sheetCols.some((c) => c.name.trim().toLowerCase() === n.trim().toLowerCase()))

  const save = async () => {
    setBusy(true); setError(null)
    try {
      const out = await bulkAdd(sheetId, { columns: extraction.columns, mapping, records: rowsToAdd, source_type: source.type, source_url: source.url || null, source_file_id: source.file_id || null })
      onSaved(out.sheet, out.added)
    } catch (e) {
      setError(errorMessage(e)); setBusy(false)
    }
  }

  const list = (ranked || []).filter((s) => s.name.toLowerCase().includes(q.trim().toLowerCase()))
  const tone = match?.suggestion === 'add' ? 'bg-emerald-500/10 text-emerald-800 dark:text-emerald-200' : match?.suggestion === 'create_new_sheet' ? 'bg-red-500/10 text-red-800 dark:text-red-200' : 'bg-amber-500/10 text-amber-800 dark:text-amber-200'

  return (
    <div>
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-2.5 h-4 w-4 text-soft" />
        <input className={`${inputCls} pl-9`} placeholder="Search your sheets" aria-label="Search your sheets" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {ranked === null ? <p className="mt-3 text-sm text-soft">Looking at your sheets…</p> : ranked.length === 0 ? (
        <p className="mt-3 text-sm text-soft">You don't have any sheets yet. <button className="text-brand underline" onClick={onChooseNew}>Create a new one</button>.</p>
      ) : (
        <ul className="mt-3 grid gap-2 sm:grid-cols-2" role="listbox" aria-label="Your sheets">
          {list.map((s, i) => (
            <li key={s.sheet_id}>
              <button role="option" aria-selected={sheetId === s.sheet_id} onClick={() => setSheetId(s.sheet_id)}
                className={`w-full rounded-md border p-3 text-left transition ${sheetId === s.sheet_id ? 'border-brand bg-brand/5' : 'border-line hover:border-brand/50'}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium">{s.name}</span>
                  {i === 0 && s.score >= 0.6 && q === '' && <span className="shrink-0 rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-700 dark:text-emerald-300">Best match</span>}
                </div>
                <p className="mt-1 text-xs text-soft">{s.matched} of {s.total} fields fit · {s.record_count} rows</p>
                <p className="mt-1 truncate text-xs text-soft">{s.column_names.join(', ') || 'No columns'}</p>
              </button>
            </li>
          ))}
          {list.length === 0 && <li className="text-sm text-soft">No sheet matches “{q}”.</li>}
        </ul>
      )}

      {matching && <p role="status" className="mt-4 flex items-center gap-2 text-sm text-soft"><Loader2 className="h-4 w-4 animate-spin" />Matching fields to columns…</p>}

      {match && (
        <div className="mt-5">
          <div role="note" className={`flex gap-2 rounded-md p-3 text-sm ${tone}`}>
            {match.suggestion === 'add' ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />}
            <div>
              <p>{match.explanation}</p>
              {match.notes.map((n) => <p key={n} className="mt-1 flex items-center gap-1"><Info className="h-3 w-3" />{n}</p>)}
              {match.suggestion === 'create_new_sheet' && <button className="mt-2 font-medium underline" onClick={onChooseNew}>Create a new sheet instead</button>}
            </div>
          </div>

          <h3 className="mt-5 text-sm font-semibold">Where each field goes in “{match.sheet.name}”</h3>
          <div className="card mt-2 overflow-x-auto">
            <table className="w-full min-w-max text-sm">
              <thead className="bg-muted text-left text-xs uppercase tracking-wide text-soft"><tr><th className="px-3 py-2">Extracted field</th><th className="px-3 py-2">Goes into</th><th className="px-3 py-2">How matched</th></tr></thead>
              <tbody>
                {extraction.columns.map((c) => {
                  const mp = match.mappings.find((x) => x.extracted === c.name)
                  const a = mapping[c.name]
                  return (
                    <tr key={c.name} className="border-t border-line">
                      <td className="px-3 py-2"><span className="font-medium">{c.name}</span> <span className="text-xs text-soft">{c.type}{withData.has(c.name) ? '' : ' · empty'}</span></td>
                      <td className="px-3 py-2">
                        <select aria-label={`Destination for ${c.name}`} className={`${inputCls} !py-1`} value={selectValue(c.name)} onChange={(e) => setAction(c.name, e.target.value)}>
                          {sheetCols.map((sc) => {
                            const other = usedBy(sc.id)
                            return <option key={sc.id} value={sc.id} disabled={!!other && other !== c.name}>{sc.name} ({sc.type}){other && other !== c.name ? ` — used by ${other}` : ''}</option>
                          })}
                          <option value="__create">➕ Create a new column “{c.name}”</option>
                          <option value="__skip">Skip this field</option>
                        </select>
                      </td>
                      <td className="px-3 py-2 text-xs text-soft">{a?.action === 'map' && mp?.sheet_column_id === a.column_id ? BADGE[mp.method] || '' : a?.action === 'map' ? 'your choice' : ''}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {skippedWithData.length > 0 && <p role="note" className="mt-2 text-sm text-amber-700 dark:text-amber-300">You chose to skip: {skippedWithData.join(', ')}. That data won't be saved.</p>}
          {nameClash && <p role="alert" className="mt-2 text-sm text-red-600">A column named “{nameClash[0]}” already exists in this sheet. Map the field to it instead of creating a new one.</p>}
          {match.unfilled_sheet_columns.length > 0 && <p className="mt-2 text-xs text-soft">These sheet columns will stay empty: {match.unfilled_sheet_columns.join(', ')}.</p>}

          {dupRows.size > 0 && (
            <div className="mt-5">
              <h3 className="flex items-center gap-2 text-sm font-semibold"><AlertTriangle className="h-4 w-4 text-amber-500" />Possible duplicates</h3>
              <ul className="mt-2 space-y-2">
                {[...dupRows.entries()].map(([i, { kind, d }]) => (
                  <li key={i} className="card flex flex-wrap items-center gap-3 p-3 text-sm">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">Row {i + 1}: {Object.values(extraction.records[i].values).filter(hasValue).slice(0, 3).join(' · ')}</p>
                      <p className="text-xs text-soft">{kind === 'existing' ? `Looks like an existing row (${Object.values(d.existing).slice(0, 3).join(' · ')}), matching on ${d.matched_columns.join(', ')}.` : `Same as row ${d.duplicate_of_row + 1} in this batch.`}</p>
                    </div>
                    <label className="flex items-center gap-2 text-xs"><input type="checkbox" className="accent-[rgb(var(--brand))]" checked={!!keepRows[i]} onChange={(e) => setKeepRows((k) => ({ ...k, [i]: e.target.checked }))} />Add anyway</label>
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-xs text-soft">Duplicates are left out unless you tick “Add anyway”.</p>
            </div>
          )}

          {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
          {(() => {
            const btn = (
              <button className="btn-primary" disabled={busy || !rowsToAdd.length || !!nameClash} onClick={save}>
                {busy ? 'Saving…' : `Add ${rowsToAdd.length} record${rowsToAdd.length === 1 ? '' : 's'} to this sheet`}
              </button>
            )
            return actionSlot ? createPortal(btn, actionSlot) : <div className="mt-5">{btn}</div>
          })()}
        </div>
      )}
      {!match && error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
    </div>
  )
}
