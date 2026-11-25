import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, CheckCircle2, Trash2, X } from 'lucide-react'
import { COLUMN_TYPES, inputCls } from '../ui'
import { errorMessage } from '../../services/api'
import { saveFromExtraction, suggestSheet } from '../../services/ai'
import ExistingSheetPanel from './ExistingSheetPanel'

const show = (v) => (v === null || v === undefined ? '' : Array.isArray(v) ? v.join(', ') : String(v))

/** Convert the API result into local editable state keyed by a stable local column id. */
export function toEditable(x) {
  const cols = x.columns.map((c, i) => ({ id: `k${i}`, name: c.name, type: c.type }))
  const byName = Object.fromEntries(cols.map((c) => [c.name, c.id]))
  const rows = x.records.map((r, ri) => ({
    id: `r${ri}`,
    values: Object.fromEntries(Object.entries(r.values).map(([n, v]) => [byName[n], show(v)])),
    meta: Object.fromEntries(Object.entries(r.meta).map(([n, m]) => [byName[n], m])),
  }))
  return { cols, rows }
}

function Chip({ children, tone = 'muted' }) {
  const t = { muted: 'bg-muted text-soft', warn: 'bg-amber-500/15 text-amber-700 dark:text-amber-300', ok: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300' }[tone]
  return <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${t}`}>{children}</span>
}

function Original({ original }) {
  if (!original) return null
  const { tab, previewUrl, fileName, url, text } = original
  let body = null
  if (tab === 'image' && previewUrl) body = <img src={previewUrl} alt="Your screenshot" className="max-h-80 w-full rounded-md border border-line object-contain" />
  else if (tab === 'url' && url) body = <a href={url} target="_blank" rel="noopener noreferrer" className="break-all text-sm text-brand underline">{url}</a>
  else if (text) body = <p className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-sm">{text}</p>
  if (!body) return null
  return (
    <aside aria-label="Original" className="min-w-0 lg:w-72 lg:shrink-0">
      <h2 className="text-sm font-semibold">Original</h2>
      <div className="card mt-2 p-3">{body}{fileName && <p className="mt-2 truncate text-xs text-soft">{fileName}</p>}</div>
    </aside>
  )
}

export default function ExtractionPreview({ result, original, onSaved, onReset }) {
  const init = useMemo(() => toEditable(result), [result])
  const [cols, setCols] = useState(init.cols)
  const [rows, setRows] = useState(init.rows)
  const [name, setName] = useState(result.suggested_sheet_name)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [dest, setDest] = useState('new') // 'new' | 'existing'
  const [similar, setSimilar] = useState(null)
  const [pickSheet, setPickSheet] = useState(null)
  const [slot, setSlot] = useState(null) // the save button of whichever destination is chosen renders into the bottom bar

  const setCell = (rid, cid, v) => setRows((rs) => rs.map((r) => (r.id === rid ? { ...r, values: { ...r.values, [cid]: v }, meta: { ...r.meta, [cid]: { ...(r.meta[cid] || {}), uncertain: false, edited: true } } } : r)))
  const setCol = (cid, patch) => setCols((cs) => cs.map((c) => (c.id === cid ? { ...c, ...patch } : c)))
  const dupNames = cols.some((c, i) => cols.findIndex((o) => o.name.trim().toLowerCase() === c.name.trim().toLowerCase()) !== i)
  const emptyName = cols.some((c) => !c.name.trim())
  const invalid = !name.trim() || !cols.length || !rows.length || dupNames || emptyName
  const pct = Math.round(result.confidence * 100)

  const extractionIn = useMemo(() => ({
    category: result.category,
    columns: cols.map((c) => ({ name: c.name.trim(), type: c.type })),
    records: rows.map((r) => ({ values: Object.fromEntries(cols.map((c) => [c.name.trim(), r.values[c.id] ?? '']).filter(([, v]) => v !== '')) })),
  }), [cols, rows, result.category])
  const namesOk = !dupNames && !emptyName && cols.length > 0 && rows.length > 0

  useEffect(() => {
    suggestSheet({ category: result.category, columns: init.cols.map((c) => ({ name: c.name, type: c.type })), records: init.rows.map((r) => ({ values: Object.fromEntries(init.cols.map((c) => [c.name, r.values[c.id] ?? '']).filter(([, v]) => v !== '')) })) })
      .then(setSimilar).catch(() => setSimilar(null))
    // suggestion is based on the extraction as first shown
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const best = similar?.similar_sheets?.[0]

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const sheet = await saveFromExtraction({
        name: name.trim(), description: result.description || null, category: result.category,
        columns: cols.map((c) => ({ name: c.name.trim(), type: c.type })),
        records: rows.map((r) => ({ values: Object.fromEntries(cols.map((c) => [c.name.trim(), r.values[c.id] ?? '']).filter(([, v]) => v !== '')) })),
        source_type: result.source.type, source_url: result.source.url || null, source_file_id: result.source.file_id || null,
      })
      onSaved(sheet)
    } catch (e) {
      setError(errorMessage(e))
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <Chip>{result.category.replace(/_/g, ' ')}</Chip>
        <Chip tone={pct >= 80 ? 'ok' : 'warn'}>{pct}% confident</Chip>
        <Chip>{rows.length} record{rows.length === 1 ? '' : 's'} found</Chip>
        {result.source.url && <a href={result.source.url} target="_blank" rel="noopener noreferrer" className="truncate text-xs text-brand underline">{result.source.url}</a>}
      </div>

      {result.warnings.length > 0 && (
        <div role="note" className="mt-4 rounded-md bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-200">
          <p className="flex items-center gap-2 font-medium"><AlertTriangle className="h-4 w-4" />Please double-check</p>
          <ul className="mt-1 list-disc pl-5">{result.warnings.map((w) => <li key={w}>{w}</li>)}{result.source.note && <li>{result.source.note}</li>}</ul>
        </div>
      )}
      {result.missing_fields.length > 0 && <p className="mt-3 text-sm text-soft">Not found in your input (left empty): {result.missing_fields.join(', ')}.</p>}

      <div className="mt-4 flex flex-col gap-5 lg:flex-row lg:items-start">
      <Original original={original} />
      <div className="min-w-0 flex-1">
      <p className="text-sm text-soft">Edit anything before saving. <span className="rounded bg-amber-500/20 px-1">Highlighted</span> cells are uncertain or were inferred by the AI.</p>
      <div className="card mt-2 overflow-x-auto">
        <table className="w-full min-w-max border-collapse text-sm">
          <thead className="bg-muted">
            <tr>
              <th className="w-10 border-b border-line" />
              {cols.map((c) => (
                <th key={c.id} className="min-w-[10rem] border-b border-l border-line p-2 text-left align-top font-medium">
                  <div className="flex items-center gap-1">
                    <input aria-label="Column name" className={`${inputCls} !px-2 !py-1 font-medium`} value={c.name} maxLength={80} onChange={(e) => setCol(c.id, { name: e.target.value })} />
                    <button aria-label={`Remove column ${c.name}`} className="text-soft hover:text-red-600" onClick={() => setCols((cs) => cs.filter((x) => x.id !== c.id))}><X className="h-4 w-4" /></button>
                  </div>
                  <select aria-label={`Type of ${c.name}`} className="mt-1 w-full rounded-lg border border-line bg-surface px-1 py-0.5 text-xs" value={c.type} onChange={(e) => setCol(c.id, { type: e.target.value })}>
                    {COLUMN_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.id}>
                <td className="border-b border-line px-2 text-center"><button aria-label={`Remove row ${i + 1}`} className="text-soft hover:text-red-600" onClick={() => setRows((rs) => rs.filter((x) => x.id !== r.id))}><Trash2 className="h-4 w-4" /></button></td>
                {cols.map((c) => {
                  const m = r.meta[c.id]
                  const flagged = m && (m.uncertain || m.origin === 'inferred') && !m.edited
                  const title = m?.raw ? `Couldn't read “${m.raw}” as ${c.type}` : flagged ? (m.origin === 'inferred' ? 'Inferred by AI, please confirm' : 'AI is not sure about this value') : undefined
                  const v = r.values[c.id] ?? ''
                  return (
                    <td key={c.id} className={`border-b border-l border-line p-1 ${flagged ? 'bg-amber-500/15' : ''}`} title={title}>
                      {flagged && <span className="block px-1 text-[10px] font-medium uppercase tracking-wide text-amber-700 dark:text-amber-300">Check</span>}
                      {c.type === 'boolean' ? (
                        <select aria-label={`${c.name} row ${i + 1}`} className={`${inputCls} !px-2 !py-1`} value={v} onChange={(e) => setCell(r.id, c.id, e.target.value)}>
                          <option value="">—</option><option value="true">Yes</option><option value="false">No</option>
                        </select>
                      ) : (
                        <input aria-label={`${c.name} row ${i + 1}`} type={c.type === 'date' ? 'date' : 'text'} className={`${inputCls} !px-2 !py-1`} value={v} placeholder={m?.raw || ''} onChange={(e) => setCell(r.id, c.id, e.target.value)} />
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      </div>
      </div>
      <h2 className="mt-8 text-lg font-semibold">Where would you like to save this?</h2>
      {best && dest === 'new' && (
        <p role="note" className="mt-2 rounded-md bg-brand/10 p-3 text-sm">
          You already have a similar sheet, “{best.name}” ({best.matched} of {best.total} fields fit).{' '}
          <button className="font-medium text-brand underline" onClick={() => { setPickSheet(best.sheet_id); setDest('existing') }}>Add it there instead</button>
        </p>
      )}
      <div role="tablist" aria-label="Save destination" className="mt-3 flex gap-6 border-b border-line">
        {[['existing', 'Add to an existing sheet'], ['new', 'Create a new sheet']].map(([id, title]) => (
          <button key={id} role="tab" aria-selected={dest === id} onClick={() => setDest(id)}
            className={`-mb-px border-b-2 py-2 text-sm font-medium transition ${dest === id ? 'border-ink text-ink' : 'border-transparent text-soft hover:text-ink'}`}>{title}</button>
        ))}
      </div>

      <div className="mt-5" role="tabpanel">
        {dest === 'new' ? (
          <>
            <div className="max-w-md">
              <label className="mb-1 block text-sm font-medium" htmlFor="sheet-name">Sheet name</label>
              <input id="sheet-name" className={inputCls} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
            </div>
            {(dupNames || emptyName) && <p role="alert" className="mt-2 text-sm text-red-600">Every column needs a unique name.</p>}
            {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
            {(() => {
              const btn = <button className="btn-primary" disabled={invalid || busy} onClick={save}>{busy ? 'Saving…' : 'Save as new sheet'}</button>
              return slot ? createPortal(btn, slot) : <div className="mt-4">{btn}</div>
            })()}
          </>
        ) : namesOk ? (
          <ExistingSheetPanel key={pickSheet || 'p'} actionSlot={slot} extraction={extractionIn} source={result.source} initialSheetId={pickSheet} onChooseNew={() => setDest('new')} onSaved={(sheet, added) => onSaved({ ...sheet, record_count: sheet.record_count, added })} />
        ) : (
          <p role="alert" className="text-sm text-red-600">Give every column a unique name and keep at least one row before choosing a sheet.</p>
        )}
      </div>
      <div className="sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] z-10 -mx-4 mt-8 flex flex-wrap items-center justify-end gap-2 border-t border-line bg-surface px-4 py-3 sm:-mx-6 sm:px-6 lg:bottom-0 lg:-mx-8 lg:-mb-8 lg:px-8">
        <span className="mr-auto hidden text-sm text-soft sm:inline">{rows.length} record{rows.length === 1 ? '' : 's'} ready to save</span>
        <button className="btn-ghost" onClick={onReset} disabled={busy}>Discard</button>
        <span ref={setSlot} className="contents" />
      </div>
    </div>
  )
}
