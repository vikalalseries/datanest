import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { usePageTitle } from '../layouts/PageTitle'
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Paperclip, Pencil, Search } from 'lucide-react'
import { Spinner } from '../components/Spinner'
import { Confirm, Empty, Modal, inputCls, useDebounced, useToast } from '../components/ui'
import { Cell } from '../components/sheet/Cell'
import { ColumnModal } from '../components/sheet/ColumnModal'
import InsightsPanel from '../components/sheet/InsightsPanel'
import { CATEGORIES } from '../services/insights'
import { FilterPanel, isComplete } from '../components/sheet/FilterPanel'
import * as S from '../services/sheets'
import { mergeSheet } from '../services/ai'
import { exportSheet, openOriginal } from '../services/files'
import { errorMessage } from '../services/api'

const LIMIT = 100

function MoveModal({ sheetId, count, onClose, onMove }) {
  const [sheets, setSheets] = useState(null)
  const [target, setTarget] = useState('')
  const [missing, setMissing] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { S.listSheets().then((l) => setSheets(l.filter((s) => s.id !== sheetId))).catch(() => setSheets([])) }, [sheetId])
  const go = async (add) => {
    setBusy(true)
    try {
      await onMove(target, add)
      onClose()
    } catch (e) {
      const err = e?.response?.data?.error
      if (err?.code === 'columns_missing') setMissing(err.missing)
      else onClose(errorMessage(e))
    } finally { setBusy(false) }
  }
  return (
    <Modal title={`Move ${count} record${count > 1 ? 's' : ''}`} onClose={() => onClose()}
      footer={<><button className="btn-ghost" onClick={() => onClose()}>Cancel</button><button className="btn-primary" disabled={!target || busy} onClick={() => go(!!missing)}>{missing ? 'Add columns and move' : 'Move'}</button></>}>
      {sheets === null ? <Spinner /> : sheets.length === 0 ? <p className="text-sm text-soft">You have no other sheets to move to.</p> : (
        <select className={inputCls} value={target} onChange={(e) => { setTarget(e.target.value); setMissing(null) }} aria-label="Target sheet">
          <option value="">Choose a sheet…</option>
          {sheets.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      )}
      {missing && <p role="alert" className="mt-3 text-sm text-amber-700 dark:text-amber-300">The target sheet has no column for: <b>{missing.join(', ')}</b>. Click “Add columns and move” to create them so no data is lost.</p>}
    </Modal>
  )
}

function MergeModal({ sheet, onClose, onDone }) {
  const [sheets, setSheets] = useState(null)
  const [source, setSource] = useState('')
  const [missing, setMissing] = useState(null)
  const [trash, setTrash] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { S.listSheets().then((l) => setSheets(l.filter((x) => x.id !== sheet.id))).catch(() => setSheets([])) }, [sheet.id])
  const go = async () => {
    setBusy(true); setError(null)
    try {
      const r = await mergeSheet(sheet.id, { source_sheet_id: source, add_missing_columns: !!missing, trash_source: trash })
      onDone(r)
    } catch (e) {
      const err = e?.response?.data?.error
      if (err?.code === 'columns_missing') setMissing(err.missing)
      else setError(errorMessage(e))
    } finally { setBusy(false) }
  }
  return (
    <Modal title="Merge another sheet into this one" onClose={onClose}
      footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={!source || busy} onClick={go}>{missing ? 'Add columns and merge' : 'Merge'}</button></>}>
      {sheets === null ? <Spinner /> : sheets.length === 0 ? <p className="text-sm text-soft">You have no other sheets to merge.</p> : (
        <>
          <select className={inputCls} value={source} aria-label="Sheet to merge in" onChange={(e) => { setSource(e.target.value); setMissing(null) }}>
            <option value="">Choose a sheet…</option>
            {sheets.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.record_count} rows)</option>)}
          </select>
          <p className="mt-2 text-xs text-soft">Rows are copied by matching column names. “{sheet.name}” keeps its columns.</p>
          {missing && <p role="alert" className="mt-3 text-sm text-amber-700 dark:text-amber-300">These sheets aren't fully compatible: “{sheet.name}” has no column for <b>{missing.join(', ')}</b>. Click “Add columns and merge” to add them so no data is lost.</p>}
          <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" className="accent-[rgb(var(--brand))]" checked={trash} onChange={(e) => setTrash(e.target.checked)} />Move the other sheet to Trash afterwards</label>
          {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
        </>
      )}
    </Modal>
  )
}

/** One table row. Memoised so editing a cell re-renders that row only, not all 100. */
const Row = memo(function Row({ r, columns, isSelected, onToggle, onEdit, onOriginal }) {
  return (
    <tr className={isSelected ? 'bg-brand/5' : 'hover:bg-muted/50'}>
      <td className="sticky left-0 z-[1] border-b border-line bg-surface px-3 py-1.5 text-center">
        <input type="checkbox" aria-label="Select row" className="accent-[rgb(var(--brand))]" checked={isSelected} onChange={() => onToggle(r.id)} />
        {r.source_file_id && <button aria-label="Download original file" title="Download the original upload" className="mt-1 block w-full text-soft hover:text-brand" onClick={() => onOriginal(r.source_file_id)}><Paperclip className="mx-auto h-3.5 w-3.5" /></button>}
      </td>
      {columns.map((c, ci) => (
        <td key={c.id} className={`border-b border-l border-line px-2 py-1 align-top ${ci === 0 ? 'sticky left-10 z-[1] bg-surface' : ''}`}>
          <Cell column={c} value={r.data[c.id]} onCommit={(raw) => onEdit(r, c, raw)} />
        </td>
      ))}
    </tr>
  )
})

/** Phone layout: one card per row, same editable cells as the table. */
const RowCard = memo(function RowCard({ r, columns, isSelected, onToggle, onEdit, onOriginal }) {
  const [first, ...rest] = columns
  return (
    <div className={`card p-3 ${isSelected ? 'border-brand' : ''}`}>
      <div className="flex items-start gap-3">
        <input type="checkbox" aria-label="Select row" className="mt-2 h-5 w-5 accent-[rgb(var(--brand))]" checked={isSelected} onChange={() => onToggle(r.id)} />
        <div className="min-w-0 flex-1 font-medium"><Cell column={first} value={r.data[first.id]} onCommit={(raw) => onEdit(r, first, raw)} /></div>
        {r.source_file_id && <button aria-label="Download original file" className="px-2 py-2 text-xs text-soft underline" onClick={() => onOriginal(r.source_file_id)}>Original</button>}
      </div>
      {rest.length > 0 && (
        <dl className="mt-2 space-y-1 border-t border-line pt-2">
          {rest.map((c) => (
            <div key={c.id} className="grid grid-cols-[6rem_minmax(0,1fr)] items-start gap-2 text-sm">
              <dt className="pt-1.5 text-[11px] uppercase tracking-wide text-soft">{c.name}</dt>
              <dd className="min-w-0"><Cell column={c} value={r.data[c.id]} onCommit={(raw) => onEdit(r, c, raw)} /></dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
})

export default function SheetEditor() {
  const { sheetId } = useParams()
  const toast = useToast()
  const [sheet, setSheet] = useState(null)
  usePageTitle(sheet?.name)
  const [error, setError] = useState(null)
  const [page, setPage] = useState({ items: [], total: 0 })
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [sort, setSort] = useState(null) // {col, dir}
  const [filters, setFilters] = useState([])
  const [showFilters, setShowFilters] = useState(false)
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState(new Set())
  const [colModal, setColModal] = useState(undefined) // undefined=closed, null=add, object=edit
  const [confirm, setConfirm] = useState(null)
  const [moving, setMoving] = useState(false)
  const [merging, setMerging] = useState(false)
  const [exportMenu, setExportMenu] = useState(false)
  const [moreMenu, setMoreMenu] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [titleEdit, setTitleEdit] = useState(null)
  const undo = useRef([])
  const [undoCount, setUndoCount] = useState(0)
  const [insightsKey, setInsightsKey] = useState(0)
  const loadedOnce = useRef(false)
  const dq = useDebounced(q)
  const activeFilters = filters.filter(isComplete)
  const fkey = JSON.stringify(activeFilters)

  const fail = useCallback((e) => toast(errorMessage(e), 'error'), [toast])
  const pushUndo = useCallback((a) => { undo.current.push(a); if (undo.current.length > 50) undo.current.shift(); setUndoCount(undo.current.length); setInsightsKey((k) => k + 1) }, [])

  useEffect(() => { S.getSheet(sheetId).then(setSheet).catch((e) => setError(errorMessage(e))) }, [sheetId])

  const load = useCallback(async (off = offset) => {
    setLoading(true)
    try {
      const params = { limit: LIMIT, offset: off }
      if (dq) params.q = dq
      if (sort) { params.sort = sort.col; params.dir = sort.dir }
      if (activeFilters.length) params.filters = JSON.stringify(activeFilters)
      const p = await S.listRecords(sheetId, params)
      setPage(p)
      // a plain reload (no search/filter/sort) follows data changes, so refresh the insights; skip the very first load
      if (loadedOnce.current && !dq && !sort && !activeFilters.length) setInsightsKey((k) => k + 1)
      loadedOnce.current = true
      if (p.items.length === 0 && off > 0) setOffset(Math.max(0, off - LIMIT))
    } catch (e) { fail(e) } finally { setLoading(false) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sheetId, dq, sort, fkey, offset, fail])

  useEffect(() => { load() }, [load])
  useEffect(() => { setOffset(0); setSelected(new Set()) }, [dq, sort, fkey])

  const columns = sheet?.columns || []

  const editCell = useCallback(async (rec, col, raw) => {
    const before = rec.data[col.id] ?? null
    try {
      const upd = await S.updateRecord(rec.id, { [col.id]: raw === '' ? null : raw })
      setPage((p) => ({ ...p, items: p.items.map((r) => (r.id === rec.id ? upd : r)) }))
      pushUndo({ kind: 'edit', id: rec.id, col: col.id, before })
    } catch (e) { fail(e) }
  }, [fail, pushUndo])
  const toggleRow = useCallback((id) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n }), [])

  const addRow = async () => {
    try {
      const r = await S.createRecord(sheetId, {})
      pushUndo({ kind: 'create', id: r.id })
      const total = page.total + 1
      const off = Math.floor((total - 1) / LIMIT) * LIMIT
      setSort(null); setQ(''); setFilters([])
      setOffset(off)
      await load(off)
    } catch (e) { fail(e) }
  }

  const deleteSelected = async () => {
    const ids = [...selected]
    try {
      const r = await S.bulkDelete(ids)
      pushUndo({ kind: 'delete', ids })
      setSelected(new Set())
      toast(`${r.deleted} record${r.deleted === 1 ? '' : 's'} moved to Trash. Press Undo to bring them back.`)
      load()
    } catch (e) { fail(e) }
  }

  const doUndo = useCallback(async () => {
    const a = undo.current.pop()
    setUndoCount(undo.current.length)
    if (!a) return
    try {
      if (a.kind === 'edit') await S.updateRecord(a.id, { [a.col]: a.before })
      if (a.kind === 'create') await S.bulkDelete([a.id])
      if (a.kind === 'delete') await S.restoreRecords(a.ids)
      toast('Undone')
      load()
    } catch (e) { fail(e) }
  }, [load, toast, fail])

  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) { e.preventDefault(); doUndo() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [doUndo])

  const saveColumn = async (body, col) => {
    try {
      const s = col ? await S.updateColumn(sheetId, col.id, body) : await S.addColumn(sheetId, body)
      setSheet(s)
      if (col && body.type !== col.type) load()
      toast(col ? 'Column updated' : 'Column added')
    } catch (e) {
      if (e?.response?.data?.error?.code === 'conversion_loses_data') {
        setConfirm({
          title: 'Some values will be cleared', danger: true, confirmLabel: 'Convert anyway',
          message: `${e.response.data.error.message} Other values are converted.`,
          onConfirm: async () => { try { setSheet(await S.updateColumn(sheetId, col.id, { ...body, force: true })); load() } catch (e2) { fail(e2) } },
        })
      } else { fail(e); throw e }
    }
  }

  const removeColumn = (col) => setConfirm({
    title: `Delete column “${col.name}”?`, danger: true, confirmLabel: 'Delete column',
    message: 'The column and all the values in it are permanently removed from every row. This can’t be undone.',
    onConfirm: async () => { try { setSheet(await S.deleteColumn(sheetId, col.id)); setColModal(undefined); load() } catch (e) { fail(e) } },
  })

  const doExport = async (fmt) => {
    setExportMenu(false); setExporting(true)
    try {
      const r = await exportSheet(sheetId, fmt)
      toast(r.truncated ? `Downloaded ${r.name} (only the first 50,000 rows were included)` : `Downloaded ${r.name}`)
    } catch (e) { fail(e) } finally { setExporting(false) }
  }
  const original = useCallback(async (fileId) => { try { await openOriginal(fileId) } catch (e) { fail(e) } }, [fail])
  const changeCategory = async (category) => {
    try { setSheet(await S.updateSheet(sheetId, { category })); setInsightsKey((k) => k + 1) } catch (e) { fail(e) }
  }

  const rename = async () => {
    const n = (titleEdit || '').trim()
    setTitleEdit(null)
    if (!n || n === sheet.name) return
    try { setSheet(await S.updateSheet(sheetId, { name: n })) } catch (e) { fail(e) }
  }

  if (error) return <p role="alert" className="text-sm text-red-600">{error} <Link to="/sheets" className="underline">Back to sheets</Link></p>
  if (!sheet) return <Spinner />

  const allSelected = page.items.length > 0 && page.items.every((r) => selected.has(r.id))
  const toggleSort = (id) => setSort((s) => (!s || s.col !== id ? { col: id, dir: 'asc' } : s.dir === 'asc' ? { col: id, dir: 'desc' } : null))
  const from = page.total === 0 ? 0 : offset + 1
  const to = Math.min(offset + LIMIT, page.total)

  const menuItem = 'block w-full rounded-md px-3 py-2 text-left text-sm hover:bg-muted'
  return (
    <div>
      <nav aria-label="Breadcrumb" className="text-sm text-soft"><Link to="/sheets" className="hover:text-ink hover:underline">Sheets</Link></nav>
      <div className="mt-1 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {titleEdit === null ? (
            <h1 className="group flex items-center gap-2 text-2xl font-semibold max-lg:sr-only">
              <span className="min-w-0 break-words">{sheet.name}</span>
              <button aria-label="Rename sheet" className="text-soft opacity-60 transition hover:opacity-100 focus:opacity-100 lg:opacity-0 lg:group-hover:opacity-100" onClick={() => setTitleEdit(sheet.name)}><Pencil className="h-4 w-4" /></button>
            </h1>
          ) : (
            <input autoFocus className={`${inputCls} !w-full text-lg font-semibold sm:!w-72`} value={titleEdit} maxLength={120} onChange={(e) => setTitleEdit(e.target.value)} onBlur={rename} onKeyDown={(e) => { if (e.key === 'Enter') rename(); if (e.key === 'Escape') setTitleEdit(null) }} />
          )}
          {sheet.description && <p className="mt-1 text-sm text-soft">{sheet.description}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <button className="btn-ghost" onClick={() => setExportMenu((m) => !m)} aria-haspopup="menu" aria-expanded={exportMenu} disabled={exporting}>{exporting ? 'Preparing…' : 'Export'}</button>
            {exportMenu && (
              <div role="menu" className="card absolute right-0 z-20 mt-1 w-44 p-1" onMouseLeave={() => setExportMenu(false)}>
                <button role="menuitem" className={menuItem} onClick={() => doExport('xlsx')}>Excel (.xlsx)</button>
                <button role="menuitem" className={menuItem} onClick={() => doExport('csv')}>CSV (.csv)</button>
              </div>
            )}
          </div>
          <div className="relative">
            <button className="btn-ghost" onClick={() => setMoreMenu((m) => !m)} aria-haspopup="menu" aria-expanded={moreMenu}>More</button>
            {moreMenu && (
              <div role="menu" className="card absolute right-0 z-20 mt-1 w-64 p-1">
                <button role="menuitem" className={menuItem} onClick={() => { setMoreMenu(false); setTitleEdit(sheet.name) }}>Rename sheet</button>
                <button role="menuitem" className={menuItem} onClick={() => { setMoreMenu(false); setColModal(null) }}>Add column</button>
                <button role="menuitem" className={menuItem} onClick={() => { setMoreMenu(false); setMerging(true) }}>Merge another sheet</button>
                <label className="mt-1 block border-t border-line px-3 pb-2 pt-2 text-xs text-soft">Category
                  <select aria-label="Sheet category" className="mt-1 w-full rounded-md border border-line bg-surface px-2 py-1.5 text-sm text-ink" value={sheet.category} onChange={(e) => changeCategory(e.target.value)}>
                    {!CATEGORIES.some(([v]) => v === sheet.category) && <option value={sheet.category}>{sheet.category.replace(/_/g, ' ')}</option>}
                    {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                  <span className="mt-1 block">Job, internship and expense categories show insights.</span>
                </label>
              </div>
            )}
            {moreMenu && <div className="fixed inset-0 z-10" aria-hidden="true" onClick={() => setMoreMenu(false)} />}
          </div>
          <button className="btn-primary" onClick={addRow} disabled={!columns.length}>Add row</button>
        </div>
      </div>
      <InsightsPanel sheetId={sheetId} refreshKey={insightsKey} />

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 sm:flex-none">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-soft" />
          <input className={`${inputCls} pl-9 sm:!w-60`} placeholder="Search this sheet" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search this sheet" />
        </div>
        <div className="relative">
          <button className="btn-ghost" onClick={() => setShowFilters((s) => !s)} aria-expanded={showFilters}>Filter{activeFilters.length > 0 && ` (${activeFilters.length})`}</button>
          {showFilters && <FilterPanel columns={columns} filters={filters} onChange={setFilters} />}
        </div>
        <select aria-label="Sort by" className="rounded-md border border-line bg-surface px-3 py-2 text-sm md:hidden" value={sort ? `${sort.col}|${sort.dir}` : ''}
          onChange={(e) => { const [col, dir] = e.target.value.split('|'); setSort(col ? { col, dir } : null) }}>
          <option value="">Sort</option>
          {columns.flatMap((c) => [<option key={`${c.id}a`} value={`${c.id}|asc`}>{c.name} (A–Z)</option>, <option key={`${c.id}d`} value={`${c.id}|desc`}>{c.name} (Z–A)</option>])}
        </select>
        <button className="btn-ghost" onClick={doUndo} disabled={!undoCount} title="Undo (Ctrl+Z)">Undo</button>
      </div>

      {selected.size > 0 && (
        <div role="region" aria-label="Selected rows" className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-line bg-muted px-3 py-2">
          <span className="mr-auto text-sm font-medium">{selected.size} selected</span>
          <button className="btn-ghost" onClick={() => setMoving(true)}>Move</button>
          <button className="btn-ghost text-red-600" onClick={() => setConfirm({ title: `Delete ${selected.size} record${selected.size > 1 ? 's' : ''}?`, danger: true, confirmLabel: 'Move to Trash', message: 'They move to Trash and can be restored.', onConfirm: deleteSelected })}>Delete</button>
          <button className="btn-ghost" onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}

      <div className="mt-4 space-y-3 md:hidden" aria-label="Rows">
        {columns.length > 0 && page.items.map((r) => (
          <RowCard key={r.id} r={r} columns={columns} isSelected={selected.has(r.id)} onToggle={toggleRow} onEdit={editCell} onOriginal={original} />
        ))}
        {columns.length > 0 && !loading && page.items.length === 0 && (
          <p className="card px-4 py-8 text-center text-sm text-soft">{dq || activeFilters.length ? 'No rows match your search or filters.' : 'No rows yet. Tap “Add row”.'}</p>
        )}
      </div>

      <div className="card mt-4 overflow-x-auto max-md:hidden">
        {columns.length === 0 ? (
          <Empty title="This sheet has no columns yet" text="Add a column to start entering data." action={<button className="btn-primary" onClick={() => setColModal(null)}>Add column</button>} />
        ) : (
          <table className="w-full min-w-max border-collapse text-sm">
            <thead className="sticky top-0 bg-muted">
              <tr>
                <th className="sticky left-0 z-[1] w-10 border-b border-line bg-muted px-3 py-2"><input type="checkbox" aria-label="Select all rows" className="accent-[rgb(var(--brand))]" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(page.items.map((r) => r.id)))} /></th>
                {columns.map((c, ci) => (
                  <th key={c.id} className={`min-w-[10rem] border-b border-l border-line px-3 py-2 text-left font-medium ${ci === 0 ? 'sticky left-10 z-[1] bg-muted' : ''}`} aria-sort={sort?.col === c.id ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                    <div className="flex items-center justify-between gap-2">
                      <button className="flex items-center gap-1 hover:text-brand" onClick={() => toggleSort(c.id)}>
                        {c.name}
                        {sort?.col === c.id && (sort.dir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                      </button>
                      <button aria-label={`Edit column ${c.name}`} className="text-soft hover:text-ink" onClick={() => setColModal(c)}><Pencil className="h-3 w-3" /></button>
                    </div>
                    <span className="text-[10px] font-normal uppercase tracking-wide text-soft">{c.type}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {page.items.map((r) => (
                <Row key={r.id} r={r} columns={columns} isSelected={selected.has(r.id)} onToggle={toggleRow} onEdit={editCell} onOriginal={original} />
              ))}
              {!loading && page.items.length === 0 && (
                <tr><td colSpan={columns.length + 1} className="px-4 py-10 text-center text-soft">{dq || activeFilters.length ? 'No rows match your search or filters.' : 'No rows yet. Click “Add row”.'}</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      <div className="mt-3 flex items-center justify-between text-sm text-soft">
        <span>{loading ? 'Loading…' : `${from}–${to} of ${page.total} rows`}</span>
        <div className="flex gap-1">
          <button className="btn-ghost !px-2" aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}><ChevronLeft className="h-4 w-4" /></button>
          <button className="btn-ghost !px-2" aria-label="Next page" disabled={offset + LIMIT >= page.total} onClick={() => setOffset(offset + LIMIT)}><ChevronRight className="h-4 w-4" /></button>
        </div>
      </div>

      {colModal !== undefined && <ColumnModal column={colModal} onClose={() => setColModal(undefined)} onSave={(b) => saveColumn(b, colModal)} onDelete={() => removeColumn(colModal)} />}
      {confirm && <Confirm {...confirm} onClose={() => setConfirm(null)} />}
      {merging && <MergeModal sheet={sheet} onClose={() => setMerging(false)} onDone={(r) => { setMerging(false); setSheet(r.sheet); toast(`Merged ${r.moved} row${r.moved === 1 ? '' : 's'}`); load() }} />}
      {moving && (
        <MoveModal sheetId={sheetId} count={selected.size} onClose={(err) => { setMoving(false); if (err) toast(err, 'error') }}
          onMove={async (target, add) => { const r = await S.moveRecords([...selected], target, add); toast(`Moved ${r.moved} record${r.moved === 1 ? '' : 's'}`); setSelected(new Set()); load() }} />
      )}
    </div>
  )
}
