import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { COLUMN_TYPES, Field, Modal, inputCls, useToast } from '../components/ui'
import { Spinner } from '../components/Spinner'
import AiStatusBanner from '../components/AiStatusBanner'
import { useElapsed } from '../hooks/useElapsed'
import { createSheet } from '../services/sheets'
import { generateTemplate, instantiateTemplate, listTemplates } from '../services/insights'
import { errorMessage } from '../services/api'

function UseModal({ template, onClose }) {
  const nav = useNavigate()
  const toast = useToast()
  const [name, setName] = useState(template.name)
  const [busy, setBusy] = useState(false)
  const go = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      const s = await instantiateTemplate(template.key, name.trim())
      nav(`/sheets/${s.id}`)
    } catch (err) { toast(errorMessage(err), 'error'); setBusy(false) }
  }
  return (
    <Modal title={`Use “${template.name}”`} onClose={onClose}
      footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button form="use-tpl" className="btn-primary" disabled={busy || !name.trim()}>Create sheet</button></>}>
      <form id="use-tpl" onSubmit={go}>
        <Field label="Sheet name"><input className={inputCls} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></Field>
        <p className="text-xs text-soft">Columns: {template.columns.map((c) => c.name).join(', ')}. You can change them any time.</p>
      </form>
    </Modal>
  )
}

function AiGenerator() {
  const nav = useNavigate()
  const [desc, setDesc] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [draft, setDraft] = useState(null)
  const [saving, setSaving] = useState(false)
  const elapsed = useElapsed(busy)

  const generate = async (e) => {
    e.preventDefault()
    setBusy(true); setError(null)
    try { setDraft(await generateTemplate(desc.trim())) } catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }
  const setCol = (i, patch) => setDraft((d) => ({ ...d, columns: d.columns.map((c, j) => (j === i ? { ...c, ...patch } : c)) }))
  const names = draft?.columns.map((c) => c.name.trim().toLowerCase()) || []
  const invalid = !draft || !draft.name.trim() || !draft.columns.length || draft.columns.some((c) => !c.name.trim()) || new Set(names).size !== names.length

  const create = async () => {
    setSaving(true); setError(null)
    try {
      const s = await createSheet({ name: draft.name.trim(), description: draft.description || null, category: draft.category, columns: draft.columns.map((c) => ({ name: c.name.trim(), type: c.type, ...(c.type === 'status' && c.options?.length ? { options: c.options } : {}) })) })
      nav(`/sheets/${s.id}`)
    } catch (err) { setError(errorMessage(err)); setSaving(false) }
  }

  return (
    <section className="card mt-8 p-5" aria-labelledby="ai-tpl">
      <h2 id="ai-tpl" className="font-semibold">Describe it, and AI designs the sheet</h2>
      <div className="mt-3"><AiStatusBanner /></div>
      {!draft ? (
        <form onSubmit={generate} className="mt-3">
          <textarea aria-label="Describe the sheet you want" className={`${inputCls} min-h-[5rem]`} maxLength={500} value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="e.g. A workout log where I track exercises, sets, reps and how I felt" />
          <button className="btn-primary mt-3" disabled={busy || desc.trim().length < 3}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{busy ? `Designing… ${elapsed}s` : 'Design my sheet'}</button>
        </form>
      ) : (
        <div className="mt-3">
          <p className="text-sm text-soft">Review and edit before creating. Nothing is saved yet.</p>
          <div className="mt-3 max-w-md"><Field label="Sheet name"><input className={inputCls} value={draft.name} maxLength={120} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></Field></div>
          <div className="card overflow-x-auto">
            <table className="w-full min-w-max text-sm">
              <thead className="bg-muted text-left text-xs uppercase tracking-wide text-soft"><tr><th className="px-3 py-2">Column</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Options</th><th /></tr></thead>
              <tbody>{draft.columns.map((c, i) => (
                <tr key={i} className="border-t border-line">
                  <td className="px-3 py-1.5"><input aria-label={`Column ${i + 1} name`} className={`${inputCls} !py-1`} value={c.name} maxLength={80} onChange={(e) => setCol(i, { name: e.target.value })} /></td>
                  <td className="px-3 py-1.5"><select aria-label={`Column ${i + 1} type`} className={`${inputCls} !py-1`} value={c.type} onChange={(e) => setCol(i, { type: e.target.value })}>{COLUMN_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></td>
                  <td className="px-3 py-1.5 text-xs text-soft">{c.type === 'status' ? (c.options || []).join(', ') || '—' : ''}</td>
                  <td className="px-2"><button aria-label={`Remove column ${c.name}`} className="text-soft hover:text-red-600" onClick={() => setDraft((d) => ({ ...d, columns: d.columns.filter((_, j) => j !== i) }))}>✕</button></td>
                </tr>))}</tbody>
            </table>
          </div>
          {invalid && <p role="alert" className="mt-2 text-sm text-red-600">Give the sheet a name and every column a unique name.</p>}
          <div className="mt-4 flex gap-2">
            <button className="btn-primary" disabled={invalid || saving} onClick={create}>{saving ? 'Creating…' : 'Create sheet'}</button>
            <button className="btn-ghost" disabled={saving} onClick={() => setDraft(null)}>Try again</button>
          </div>
        </div>
      )}
      {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
    </section>
  )
}

export default function Templates() {
  const [templates, setTemplates] = useState(null)
  const [error, setError] = useState(null)
  const [using, setUsing] = useState(null)
  useEffect(() => { listTemplates().then(setTemplates).catch((e) => setError(errorMessage(e))) }, [])
  return (
    <div>
      <h1 className="text-2xl font-semibold max-lg:sr-only">Templates</h1>
      <p className="mt-1 text-soft">Start from a ready-made sheet, or let AI design one for you.</p>
      {error ? <p role="alert" className="mt-5 text-sm text-red-600">{error}</p> : !templates ? <div className="mt-6"><Spinner /></div> : (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {templates.map((t) => {
            return (
              <div key={t.key} className="card flex flex-col p-5">
                <h3 className="font-semibold">{t.name}</h3>
                <p className="mt-1 flex-1 text-sm text-soft">{t.description}</p>
                <p className="mt-3 line-clamp-2 text-xs text-soft">{t.columns.map((c) => c.name).join(' · ')}</p>
                <button className="btn-ghost mt-4" onClick={() => setUsing(t)} aria-label={`Use ${t.name}`}>Use template</button>
              </div>
            )
          })}
        </div>
      )}
      <AiGenerator />
      {using && <UseModal template={using} onClose={() => setUsing(null)} />}
    </div>
  )
}
