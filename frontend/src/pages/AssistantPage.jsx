import { useEffect, useRef, useState } from 'react'
import { Loader2, Send } from 'lucide-react'
import AiStatusBanner from '../components/AiStatusBanner'
import ProposalCard from '../components/assistant/ProposalCard'
import { useElapsed } from '../hooks/useElapsed'
import RichText from '../components/assistant/RichText'
import { inputCls } from '../components/ui'
import { SUGGESTIONS, sendChat, toHistory } from '../services/assistant'
import { errorMessage } from '../services/api'

const KEY = 'datanest-assistant-chat'
const show = (v) => (Array.isArray(v) ? v.join(', ') : v === null || v === undefined ? '' : String(v))

function load() {
  try { return JSON.parse(sessionStorage.getItem(KEY) || '[]') } catch { return [] }
}
function save(messages) {
  try { sessionStorage.setItem(KEY, JSON.stringify(messages.slice(-40))) } catch { /* storage unavailable: chat still works */ }
}

function ResultTable({ t }) {
  return (
    <div className="mt-3">
      <p className="mb-1 text-xs font-medium text-soft">{t.title} · showing {t.rows.length} of {t.total}</p>
      <div className="max-h-72 overflow-auto rounded-md border border-line">
        <table className="w-full min-w-max text-sm">
          <thead className="sticky top-0 bg-muted text-left"><tr>{t.columns.map((c) => <th key={c} className="px-3 py-1.5 font-medium">{c}</th>)}</tr></thead>
          <tbody>{t.rows.map((r, i) => <tr key={i} className="border-t border-line">{t.columns.map((c) => <td key={c} className="max-w-[16rem] truncate px-3 py-1.5">{show(r[c])}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </div>
  )
}

export default function AssistantPage() {
  const [messages, setMessages] = useState(load)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef(null)
  const elapsed = useElapsed(busy)

  useEffect(() => { save(messages) }, [messages])
  useEffect(() => { endRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' }) }, [messages, busy])

  const send = async (text) => {
    const message = (text ?? input).trim()
    if (!message || busy) return
    const history = toHistory(messages)
    setInput('')
    setMessages((m) => [...m, { id: crypto.randomUUID(), role: 'user', text: message }])
    setBusy(true)
    try {
      const r = await sendChat(message, history)
      setMessages((m) => [...m, { id: crypto.randomUUID(), role: 'assistant', text: r.reply, tables: r.tables, proposals: r.proposals.map((p) => ({ ...p, ui: { status: 'pending' } })), trace: r.tool_trace }])
    } catch (e) {
      setMessages((m) => [...m, { id: crypto.randomUUID(), role: 'assistant', text: errorMessage(e), error: true }])
    } finally { setBusy(false) }
  }

  const setProposalState = (mid, pid, ui) =>
    setMessages((ms) => ms.map((m) => (m.id === mid ? { ...m, proposals: m.proposals.map((p) => (p.id === pid ? { ...p, ui } : p)) } : m)))

  return (
    <div className="mx-auto flex max-w-5xl flex-col" style={{ minHeight: 'calc(100vh - 9rem)' }}>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold max-lg:sr-only">Assistant</h1>
        {messages.length > 0 && <button className="btn-ghost" onClick={() => setMessages([])} disabled={busy}>Clear chat</button>}
      </div>
      <p className="mt-1 text-sm text-soft">Ask questions about your sheets. The assistant reads only your own data, can't change anything by itself, and asks you to confirm before it creates or adds anything.</p>

      <div className="mt-4"><AiStatusBanner /></div>
      <div className="mt-5 flex-1 space-y-4" aria-live="polite">
        {messages.length === 0 && (
          <div className="card p-5">
            <p className="font-medium">Try asking</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => <button key={s} className="rounded-md border border-line px-3 py-1.5 text-left text-sm text-soft hover:border-brand hover:text-brand" onClick={() => send(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : ''}`}>
            <div className={`min-w-0 max-w-[92%] rounded-lg px-4 py-3 sm:max-w-[85%] ${m.role === 'user' ? 'bg-brand/10' : m.error ? 'border border-red-500/40 bg-red-500/5' : 'card'}`}>
              {m.role === 'user' ? <p className="whitespace-pre-wrap text-sm">{m.text}</p> : m.error ? <p role="alert" className="text-sm text-red-700 dark:text-red-300">{m.text}</p> : <RichText text={m.text} />}
              {m.tables?.map((t, i) => <ResultTable key={i} t={t} />)}
              {m.proposals?.map((p) => <ProposalCard key={p.id} proposal={p} state={p.ui} onState={(ui) => setProposalState(m.id, p.id, ui)} />)}
              {m.trace?.length > 0 && <p className="mt-3 text-xs text-soft">{[...new Set(m.trace.map((t) => t.summary))].join(' · ')}</p>}
            </div>
          </div>
        ))}
        {busy && <p role="status" className="flex items-center gap-2 text-sm text-soft"><Loader2 className="h-4 w-4 animate-spin" />Looking through your data… {elapsed}s{elapsed >= 12 ? ' (the AI is slow right now)' : ''}</p>}
        <div ref={endRef} />
      </div>

      <form className="sticky bottom-16 mt-4 lg:bottom-0 flex items-end gap-2 border-t border-line bg-bg pb-2 pt-3" onSubmit={(e) => { e.preventDefault(); send() }}>
        <textarea aria-label="Message the assistant" rows={1} className={`${inputCls} max-h-40 min-h-[2.75rem] resize-none`} placeholder="Ask about your sheets…" value={input} maxLength={2000}
          onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
        <button className="btn-primary h-11" disabled={busy || !input.trim()} aria-label="Send"><Send className="h-4 w-4" /></button>
      </form>
    </div>
  )
}
