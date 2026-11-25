import { useState } from 'react'
import { COLUMN_TYPES, Field, Modal, inputCls } from '../ui'

/** Used for both "Add column" (column=null) and editing an existing column. */
export function ColumnModal({ column, onClose, onSave, onDelete }) {
  const [name, setName] = useState(column?.name || '')
  const [type, setType] = useState(column?.type || 'text')
  const [options, setOptions] = useState((column?.options || []).join(', '))
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    const body = { name: name.trim(), type }
    if (type === 'status') body.options = options.split(',').map((o) => o.trim()).filter(Boolean)
    try {
      await onSave(body)
      onClose()
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title={column ? 'Edit column' : 'Add column'}
      onClose={onClose}
      footer={
        <>
          {column && <button type="button" className="btn mr-auto text-red-600 hover:bg-muted" onClick={onDelete}>Delete column</button>}
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button form="col-form" className="btn-primary" disabled={busy || !name.trim()}>{column ? 'Save' : 'Add column'}</button>
        </>
      }
    >
      <form id="col-form" onSubmit={submit}>
        <Field label="Name"><input className={inputCls} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Type">
          <select className={inputCls} value={type} onChange={(e) => setType(e.target.value)}>
            {COLUMN_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        {type === 'status' && (
          <Field label="Suggested values (comma separated)">
            <input className={inputCls} value={options} onChange={(e) => setOptions(e.target.value)} placeholder="Applied, Interview, Offer, Rejected" />
          </Field>
        )}
        {column && type !== column.type && <p className="text-xs text-soft">Existing values are converted. If some can't be, you'll be asked before they are cleared.</p>}
      </form>
    </Modal>
  )
}
