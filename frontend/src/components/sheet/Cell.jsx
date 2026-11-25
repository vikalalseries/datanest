import { useEffect, useRef, useState } from 'react'

const toText = (type, v) => {
  if (v === null || v === undefined) return ''
  if (type === 'tags') return Array.isArray(v) ? v.join(', ') : String(v)
  return String(v)
}

function Display({ type, value }) {
  if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) return <span className="text-soft/50">—</span>
  if (type === 'tags')
    return <span className="flex flex-wrap gap-1">{value.map((t) => <span key={t} className="rounded-md bg-brand/10 px-1.5 py-0.5 text-xs text-brand">{t}</span>)}</span>
  if (type === 'status') return <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium">{value}</span>
  if (type === 'url') return <a href={value} target="_blank" rel="noopener noreferrer" className="text-brand underline" onClick={(e) => e.stopPropagation()}>{value}</a>
  if (type === 'email') return <a href={`mailto:${value}`} className="text-brand underline" onClick={(e) => e.stopPropagation()}>{value}</a>
  if (type === 'number' || type === 'currency') return <span className="tabular-nums">{Number(value).toLocaleString()}</span>
  return <span className="whitespace-pre-wrap break-words">{String(value)}</span>
}

/** Click-to-edit cell. `onCommit(raw)` returns a promise; on failure the parent shows the error and the value reverts. */
export function Cell({ column, value, onCommit }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const ref = useRef(null)
  const listId = `opts-${column.id}`

  useEffect(() => { if (editing) ref.current?.focus() }, [editing])

  if (column.type === 'boolean')
    return (
      <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--brand))]" checked={value === true} aria-label={column.name}
        onChange={(e) => onCommit(e.target.checked)} />
    )

  const start = () => { setDraft(toText(column.type, value)); setEditing(true) }
  const finish = (save) => {
    setEditing(false)
    if (save && draft !== toText(column.type, value)) onCommit(draft)
  }

  if (!editing)
    return (
      <div tabIndex={0} role="button" aria-label={`Edit ${column.name}`} className="min-h-[1.75rem] cursor-text rounded px-1 py-1 focus:outline-none focus:ring-2 focus:ring-brand"
        onClick={start} onKeyDown={(e) => (e.key === 'Enter' || e.key === 'F2') && start()}>
        <Display type={column.type} value={value} />
      </div>
    )

  const type = column.type === 'date' ? 'date' : 'text'
  return (
    <>
      <input
        ref={ref} type={type} value={draft} list={column.type === 'status' && column.options?.length ? listId : undefined}
        inputMode={column.type === 'number' || column.type === 'currency' ? 'decimal' : undefined}
        placeholder={column.type === 'tags' ? 'comma, separated' : undefined}
        className="w-full rounded border border-brand bg-surface px-1 py-1 text-sm outline-none"
        onChange={(e) => setDraft(e.target.value)} onBlur={() => finish(true)}
        onKeyDown={(e) => { if (e.key === 'Enter') finish(true); if (e.key === 'Escape') finish(false) }}
      />
      {column.type === 'status' && column.options?.length > 0 && <datalist id={listId}>{column.options.map((o) => <option key={o} value={o} />)}</datalist>}
    </>
  )
}
