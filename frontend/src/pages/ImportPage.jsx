import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Loader2, UploadCloud } from 'lucide-react'
import { COLUMN_TYPES, inputCls, useToast } from '../components/ui'
import { checkImportFile, commitImport, previewImport } from '../services/files'
import { errorMessage } from '../services/api'

export default function ImportPage() {
  const nav = useNavigate()
  const toast = useToast()
  const fileRef = useRef(null)
  const [file, setFile] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [preview, setPreview] = useState(null)
  const [wsIndex, setWsIndex] = useState(0)
  const [sheetName, setSheetName] = useState('')
  const [cols, setCols] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const ws = preview?.worksheets[wsIndex]

  const loadWorksheet = (p, i, f) => {
    const w = p.worksheets[i]
    setWsIndex(i)
    const base = (f?.name || 'Imported data').replace(/\.[^.]+$/, '')
    setSheetName(p.worksheets.length > 1 ? `${base} - ${w.name}`.slice(0, 120) : base.slice(0, 120))
    setCols(w.columns.map((c, index) => ({ index, name: c.name, type: c.type, include: true, note: c.note })))
  }

  const pick = async (f) => {
    setError(null)
    const problem = checkImportFile(f)
    if (problem) { setError(problem); return }
    setFile(f); setBusy(true); setPreview(null)
    try {
      const p = await previewImport(f)
      setPreview(p)
      loadWorksheet(p, 0, f)
    } catch (e) {
      setError(errorMessage(e)); setFile(null)
    } finally { setBusy(false) }
  }

  const reset = () => { setFile(null); setPreview(null); setError(null) }
  const included = cols.filter((c) => c.include)
  const names = included.map((c) => c.name.trim().toLowerCase())
  const dup = new Set(names).size !== names.length
  const blank = included.some((c) => !c.name.trim())
  const canImport = !!ws && included.length > 0 && !dup && !blank && sheetName.trim() && ws.row_count > 0
  const setCol = (i, patch) => setCols((cs) => cs.map((c, j) => (j === i ? { ...c, ...patch } : c)))

  const doImport = async () => {
    setBusy(true); setError(null)
    try {
      const sheet = await commitImport(file, {
        worksheet: ws.name, sheet_name: sheetName.trim(),
        columns: cols.map((c) => ({ index: c.index, name: c.name.trim() || `Column ${c.index + 1}`, type: c.type, include: c.include })),
      })
      toast(`Imported ${sheet.record_count} row${sheet.record_count === 1 ? '' : 's'} into “${sheet.name}”`)
      nav(`/sheets/${sheet.id}`)
    } catch (e) {
      setError(errorMessage(e)); setBusy(false)
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold max-lg:sr-only">Import a spreadsheet</h1>
      <p className="mt-1 text-soft">Upload an Excel (.xlsx) or CSV file, review how it will be read, then create a sheet from it. Nothing is saved until you confirm.</p>

      {!preview && (
        <div className="card mt-6 p-5">
          <div role="button" tabIndex={0} aria-label="Upload a spreadsheet file"
            onClick={() => fileRef.current?.click()} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && fileRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0]) }}
            className={`grid cursor-pointer place-items-center rounded-md border border-dashed px-6 py-12 text-center transition ${dragging ? 'border-brand bg-brand/5' : 'border-line hover:border-brand/60'}`}>
            <div><UploadCloud className="mx-auto h-8 w-8 text-soft" /><p className="mt-2 font-medium">Drop a file here, or click to browse</p><p className="text-sm text-soft">.xlsx or .csv, up to 10 MB and 5,000 rows</p></div>
            <input ref={fileRef} type="file" accept=".xlsx,.csv" className="hidden" onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
          </div>
          {busy && <p role="status" className="mt-4 flex items-center gap-2 text-sm text-soft"><Loader2 className="h-4 w-4 animate-spin" />Reading your file…</p>}
        </div>
      )}
      {error && <p role="alert" className="mt-4 rounded-md bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-300">{error}</p>}

      {preview && ws && (
        <div className="mt-6">
          <p className="text-sm text-soft">{preview.filename} · {ws.row_count} row{ws.row_count === 1 ? '' : 's'} found</p>
          {preview.worksheets.length > 1 && (
            <div className="mt-3 max-w-sm">
              <label htmlFor="ws" className="mb-1 block text-sm font-medium">Worksheet</label>
              <select id="ws" className={inputCls} value={wsIndex} onChange={(e) => loadWorksheet(preview, Number(e.target.value), file)}>
                {preview.worksheets.map((w, i) => <option key={w.name} value={i}>{w.name} ({w.row_count} rows)</option>)}
              </select>
            </div>
          )}
          {ws.warnings.length > 0 && (
            <div role="note" className="mt-4 rounded-md bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-200">
              <p className="flex items-center gap-2 font-medium"><AlertTriangle className="h-4 w-4" />Please note</p>
              <ul className="mt-1 list-disc pl-5">{ws.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
            </div>
          )}
          <div className="mt-4 max-w-md">
            <label htmlFor="sname" className="mb-1 block text-sm font-medium">Sheet name</label>
            <input id="sname" className={inputCls} value={sheetName} maxLength={120} onChange={(e) => setSheetName(e.target.value)} />
          </div>

          <h2 className="mt-6 text-sm font-semibold">Columns</h2>
          <div className="card mt-2 overflow-x-auto">
            <table className="w-full min-w-max text-sm">
              <thead className="bg-muted text-left text-xs uppercase tracking-wide text-soft"><tr><th className="px-3 py-2">Import</th><th className="px-3 py-2">Name</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Preview</th></tr></thead>
              <tbody>
                {cols.map((c, i) => (
                  <tr key={c.index} className={`border-t border-line ${c.include ? '' : 'opacity-50'}`}>
                    <td className="px-3 py-2"><input type="checkbox" aria-label={`Import column ${c.name}`} className="accent-[rgb(var(--brand))]" checked={c.include} onChange={(e) => setCol(i, { include: e.target.checked })} /></td>
                    <td className="px-3 py-2"><input aria-label={`Name of column ${i + 1}`} className={`${inputCls} !py-1`} value={c.name} maxLength={80} onChange={(e) => setCol(i, { name: e.target.value })} /></td>
                    <td className="px-3 py-2">
                      <select aria-label={`Type of ${c.name}`} className={`${inputCls} !py-1`} value={c.type} onChange={(e) => setCol(i, { type: e.target.value })}>{COLUMN_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
                      {c.note && <p className="mt-1 max-w-[16rem] text-xs text-amber-700 dark:text-amber-300">{c.note}</p>}
                    </td>
                    <td className="max-w-[18rem] truncate px-3 py-2 text-soft">{ws.sample_rows.slice(0, 3).map((r) => r[c.index]).filter((v) => v !== null && v !== '').join(' · ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(dup || blank) && <p role="alert" className="mt-2 text-sm text-red-600">Every imported column needs a unique name.</p>}

          <h2 className="mt-6 text-sm font-semibold">First rows</h2>
          <div className="card mt-2 max-h-72 overflow-auto">
            <table className="w-full min-w-max text-sm">
              <thead className="sticky top-0 bg-muted text-left"><tr>{ws.columns.map((c) => <th key={c.name} className="px-3 py-2 font-medium">{c.name}</th>)}</tr></thead>
              <tbody>{ws.sample_rows.map((r, i) => <tr key={i} className="border-t border-line">{r.map((v, j) => <td key={j} className="max-w-[16rem] truncate px-3 py-1.5">{v === null ? '' : String(v)}</td>)}</tr>)}</tbody>
            </table>
          </div>
          {ws.row_count > ws.sample_rows.length && <p className="mt-1 text-xs text-soft">Showing {ws.sample_rows.length} of {ws.row_count} rows.</p>}

          <div className="mt-6 flex flex-wrap gap-2">
            <button className="btn-primary" disabled={!canImport || busy} onClick={doImport}>{busy ? 'Importing…' : `Import ${ws.row_count} row${ws.row_count === 1 ? '' : 's'}`}</button>
            <button className="btn-ghost" disabled={busy} onClick={reset}>Choose another file</button>
          </div>
        </div>
      )}
    </div>
  )
}
