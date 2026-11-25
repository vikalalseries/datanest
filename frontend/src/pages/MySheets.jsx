import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Confirm, Empty, Field, Modal, inputCls, useDebounced, useToast } from '../components/ui'
import { Spinner } from '../components/Spinner'
import { createSheet, duplicateSheet, listSheets, trashSheet, updateSheet } from '../services/sheets'
import { categoryLabel } from '../services/insights'
import { errorMessage } from '../services/api'

function NewSheetModal({ onClose }) {
  const nav = useNavigate()
  const toast = useToast()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    try {
      const s = await createSheet({ name: name.trim(), description: description.trim() || null, columns: [{ name: 'Name', type: 'text' }] })
      nav(`/sheets/${s.id}`)
    } catch (err) {
      toast(errorMessage(err), 'error')
      setBusy(false)
    }
  }
  return (
    <Modal
      title="New sheet"
      onClose={onClose}
      footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button form="new-sheet" className="btn-primary" disabled={busy || !name.trim()}>Create sheet</button></>}
    >
      <form id="new-sheet" onSubmit={submit}>
        <Field label="Name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="e.g. Internship applications" /></Field>
        <Field label="Description (optional)"><input className={inputCls} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} /></Field>
        <p className="text-xs text-soft">You can add and change columns any time.</p>
      </form>
    </Modal>
  )
}

const COLS = 'grid grid-cols-[minmax(0,1fr)_4rem_2rem] items-center gap-3 px-4 sm:grid-cols-[minmax(0,1fr)_9rem_4rem_7rem_2rem] lg:grid-cols-[minmax(0,1fr)_11rem_5rem_8rem_2rem]'

function SheetRow({ sheet, onChanged }) {
  const toast = useToast()
  const [menu, setMenu] = useState(false)
  const [rename, setRename] = useState(null)
  const [del, setDel] = useState(false)
  const act = async (fn, ok) => {
    try { await fn(); if (ok) toast(ok); onChanged() } catch (e) { toast(errorMessage(e), 'error') }
  }
  const item = 'block w-full rounded-md px-3 py-2 text-left text-sm hover:bg-muted'
  return (
    <li className={`${COLS} relative py-3 hover:bg-muted/50`}>
      <Link to={`/sheets/${sheet.id}`} className="min-w-0">
        <span className="block truncate font-medium">{sheet.name}</span>
        <span className="block truncate text-xs text-soft">{sheet.description || `${sheet.columns.length} columns`}</span>
      </Link>
      <span className="hidden truncate text-sm text-soft sm:block">{categoryLabel(sheet.category)}</span>
      <span className="text-right text-sm tabular-nums">{sheet.record_count}</span>
      <span className="hidden text-sm text-soft sm:block">{new Date(sheet.updated_at).toLocaleDateString()}</span>
      <button className="rounded-md px-1 py-1 text-soft hover:bg-muted hover:text-ink" onClick={() => setMenu((m) => !m)} aria-haspopup="menu" aria-expanded={menu} aria-label={`Actions for ${sheet.name}`}>•••</button>
      {menu && (
        <>
          <div className="fixed inset-0 z-10" aria-hidden="true" onClick={() => setMenu(false)} />
          <div role="menu" className="card absolute right-3 top-full z-20 w-40 p-1">
            <button role="menuitem" className={item} onClick={() => { setMenu(false); setRename(sheet.name) }}>Rename</button>
            <button role="menuitem" className={item} onClick={() => { setMenu(false); act(() => duplicateSheet(sheet.id), 'Sheet duplicated') }}>Duplicate</button>
            <button role="menuitem" className={`${item} text-red-600`} onClick={() => { setMenu(false); setDel(true) }}>Delete</button>
          </div>
        </>
      )}
      {rename !== null && (
        <Modal title="Rename sheet" onClose={() => setRename(null)} footer={<><button className="btn-ghost" onClick={() => setRename(null)}>Cancel</button><button form={`rn-${sheet.id}`} className="btn-primary" disabled={!rename.trim()}>Save</button></>}>
          <form id={`rn-${sheet.id}`} onSubmit={(e) => { e.preventDefault(); const n = rename.trim(); setRename(null); act(() => updateSheet(sheet.id, { name: n }), 'Sheet renamed') }}>
            <input className={inputCls} value={rename} onChange={(e) => setRename(e.target.value)} maxLength={120} aria-label="Sheet name" />
          </form>
        </Modal>
      )}
      {del && <Confirm danger title="Delete sheet?" confirmLabel="Move to Trash" message={`“${sheet.name}” and its ${sheet.record_count} records will move to Trash. You can restore it from there.`} onConfirm={() => act(() => trashSheet(sheet.id), 'Moved to Trash')} onClose={() => setDel(false)} />}
    </li>
  )
}

export default function MySheets() {
  const [sheets, setSheets] = useState(null)
  const [error, setError] = useState(null)
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('all')
  const [creating, setCreating] = useState(false)
  const dq = useDebounced(q)
  const load = useCallback(() => {
    listSheets(dq).then((s) => { setSheets(s); setError(null) }).catch((e) => setError(errorMessage(e)))
  }, [dq])
  useEffect(load, [load])

  const categories = useMemo(() => [...new Set((sheets || []).map((s) => s.category))], [sheets])
  const shown = (sheets || []).filter((s) => cat === 'all' || s.category === cat)
  const activeCat = cat === 'all' || categories.includes(cat) ? cat : 'all'

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold max-lg:sr-only">Sheets</h1>
        <div className="flex flex-wrap gap-2">
          <Link to="/import" className="btn-ghost">Import</Link>
          <button className="btn-primary" onClick={() => setCreating(true)}>New sheet</button>
        </div>
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <input className={`${inputCls} sm:!w-64`} placeholder="Search sheets" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search sheets" />
        {categories.length > 1 && (
          <div role="group" aria-label="Filter by category" className="flex flex-wrap gap-1.5">
            {['all', ...categories].map((c) => (
              <button key={c} aria-pressed={activeCat === c} onClick={() => setCat(c)}
                className={`rounded-md border px-2.5 py-1 text-xs transition ${activeCat === c ? 'border-ink bg-ink text-bg' : 'border-line text-soft hover:text-ink'}`}>
                {c === 'all' ? 'All' : categoryLabel(c)}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="mt-5">
        {error ? <p role="alert" className="text-sm text-red-600">{error}</p> : sheets === null ? <Spinner /> : sheets.length === 0 ? (
          <Empty title={dq ? 'No sheets match your search' : 'No sheets yet'} text={dq ? undefined : 'Create your first sheet to start organizing records.'} action={!dq && <button className="btn-primary" onClick={() => setCreating(true)}>New sheet</button>} />
        ) : (
          <div className="card">
            <div className={`${COLS} border-b border-line bg-muted py-2 text-xs font-medium text-soft`} aria-hidden="true">
              <span>Name</span><span className="hidden sm:block">Category</span><span className="text-right">Rows</span><span className="hidden sm:block">Updated</span><span />
            </div>
            <ul className="divide-y divide-line">
              {shown.map((s) => <SheetRow key={s.id} sheet={s} onChanged={load} />)}
            </ul>
          </div>
        )}
      </div>
      {creating && <NewSheetModal onClose={() => setCreating(false)} />}
    </div>
  )
}
