import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, Loader2, ShieldCheck, X } from 'lucide-react'
import { confirmAction } from '../../services/assistant'
import { errorMessage } from '../../services/api'

const show = (v) => (Array.isArray(v) ? v.join(', ') : v === null || v === undefined ? '' : String(v))

/** The assistant only PROPOSES. Nothing is saved until the user presses Confirm here. */
export default function ProposalCard({ proposal, state, onState }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const status = state?.status || 'pending'

  const confirm = async () => {
    setBusy(true); setError(null)
    try {
      const r = await confirmAction(proposal.payload)
      onState({ status: 'done', result: r })
    } catch (e) {
      setError(errorMessage(e)); setBusy(false)
    }
  }

  return (
    <div className="card mt-3 border-brand/40 p-4" role="group" aria-label={proposal.title}>
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-brand"><ShieldCheck className="h-4 w-4" />Proposal · not saved yet</div>
      <p className="mt-1 font-medium">{proposal.title}</p>
      {proposal.type === 'create_sheet' && (
        <p className="mt-1 text-xs text-soft">Columns: {proposal.columns.map((c) => `${c} (${proposal.column_types?.[c] || 'text'})`).join(', ')}</p>
      )}
      {proposal.rows.length > 0 && (
        <div className="mt-3 max-h-56 overflow-auto rounded-md border border-line">
          <table className="w-full min-w-max text-sm">
            <thead className="sticky top-0 bg-muted text-left"><tr>{proposal.columns.map((c) => <th key={c} className="px-3 py-1.5 font-medium">{c}</th>)}</tr></thead>
            <tbody>{proposal.rows.map((r, i) => <tr key={i} className="border-t border-line">{proposal.columns.map((c) => <td key={c} className="max-w-[14rem] truncate px-3 py-1.5">{show(r[c])}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
      {status === 'pending' && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button className="btn-primary" onClick={confirm} disabled={busy}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}{proposal.type === 'create_sheet' ? 'Create sheet' : 'Add to sheet'}</button>
          <button className="btn-ghost" onClick={() => onState({ status: 'dismissed' })} disabled={busy}><X className="h-4 w-4" />Dismiss</button>
          {error && <span role="alert" className="text-sm text-red-600">{error}</span>}
        </div>
      )}
      {status === 'done' && (
        <p className="mt-3 flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-300"><CheckCircle2 className="h-4 w-4" />
          {proposal.type === 'create_sheet' ? 'Sheet created' : `Added ${state.result.added} record${state.result.added === 1 ? '' : 's'}`}.{' '}
          <Link className="underline" to={`/sheets/${state.result.sheet_id}`}>Open “{state.result.sheet_name}”</Link>
        </p>
      )}
      {status === 'dismissed' && <p className="mt-3 text-sm text-soft">Dismissed. Nothing was saved.</p>}
    </div>
  )
}
