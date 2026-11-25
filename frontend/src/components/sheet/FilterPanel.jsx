import { Plus, X } from 'lucide-react'
import { inputCls } from '../ui'

const OPS = {
  text: [['contains', 'contains'], ['eq', 'is'], ['neq', 'is not'], ['empty', 'is empty'], ['notempty', 'is not empty']],
  num: [['eq', '='], ['gt', '>'], ['gte', '≥'], ['lt', '<'], ['lte', '≤'], ['empty', 'is empty'], ['notempty', 'is not empty']],
  bool: [['eq', 'is']],
}
const opsFor = (t) => (['number', 'currency', 'date'].includes(t) ? OPS.num : t === 'boolean' ? OPS.bool : OPS.text)

/** A filter is only sent to the server once it is complete. */
export const isComplete = (f) => f.column && f.op && (f.op === 'empty' || f.op === 'notempty' || (f.value !== '' && f.value !== undefined))

export function FilterPanel({ columns, filters, onChange }) {
  const set = (i, patch) => onChange(filters.map((f, j) => (j === i ? { ...f, ...patch } : f)))
  const add = () => columns.length && onChange([...filters, { column: columns[0].id, op: opsFor(columns[0].type)[0][0], value: '' }])
  return (
    <div className="card absolute right-0 z-20 mt-2 w-[min(32rem,92vw)] p-4">
      {filters.length === 0 && <p className="mb-3 text-sm text-soft">No filters. Add one to narrow down the rows.</p>}
      {filters.map((f, i) => {
        const col = columns.find((c) => c.id === f.column) || columns[0]
        const noValue = f.op === 'empty' || f.op === 'notempty'
        return (
          <div key={i} className="mb-2 flex flex-wrap items-center gap-2">
            <select aria-label="Filter column" className={`${inputCls} !w-auto flex-1`} value={f.column}
              onChange={(e) => { const c = columns.find((x) => x.id === e.target.value); set(i, { column: c.id, op: opsFor(c.type)[0][0], value: '' }) }}>
              {columns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <select aria-label="Filter operator" className={`${inputCls} !w-auto`} value={f.op} onChange={(e) => set(i, { op: e.target.value })}>
              {opsFor(col.type).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            {!noValue && (col.type === 'boolean' ? (
              <select aria-label="Filter value" className={`${inputCls} !w-auto`} value={String(f.value)} onChange={(e) => set(i, { value: e.target.value === 'true' })}>
                <option value="">Choose…</option><option value="true">Yes</option><option value="false">No</option>
              </select>
            ) : (
              <input aria-label="Filter value" className={`${inputCls} !w-32`} type={col.type === 'date' ? 'date' : 'text'} value={f.value} onChange={(e) => set(i, { value: e.target.value })} />
            ))}
            <button aria-label="Remove filter" className="text-soft hover:text-ink" onClick={() => onChange(filters.filter((_, j) => j !== i))}><X className="h-4 w-4" /></button>
          </div>
        )
      })}
      <button className="btn-ghost mt-1" onClick={add} disabled={!columns.length}><Plus className="h-4 w-4" />Add filter</button>
    </div>
  )
}
