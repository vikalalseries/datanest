import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, UploadCloud } from 'lucide-react'
import AiStatusBanner from '../components/AiStatusBanner'
import ExtractionPreview from '../components/extraction/ExtractionPreview'
import { useElapsed } from '../hooks/useElapsed'
import { inputCls, useToast } from '../components/ui'
import { checkImage, extractImage, extractText, extractUrl } from '../services/ai'
import { errorMessage } from '../services/api'

const TABS = [
  { id: 'image', label: 'Screenshot' },
  { id: 'url', label: 'Link' },
  { id: 'text', label: 'Text' },
]
const EXAMPLES = [
  'I applied for a Generative AI internship at Dobbe AI on 23 November 2026. The position is AI Intern. I found the job through LinkedIn.',
  'I spent 500 rupees on internet recharge on 20 November.',
  'Create a record for my college assignment. Subject Biology, deadline 30 November 2026, status pending.',
]

export default function SmartAdd() {
  const nav = useNavigate()
  const toast = useToast()
  const [tab, setTab] = useState('text')
  const [file, setFile] = useState(null)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [url, setUrl] = useState('')
  const [text, setText] = useState('')
  const [pageSourceUrl, setPageSourceUrl] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [needsText, setNeedsText] = useState(false)
  const [errorCode, setErrorCode] = useState(null)
  const lastRun = useRef(null)
  const elapsed = useElapsed(busy)
  const [result, setResult] = useState(null)
  const fileRef = useRef(null)
  const exampleIdx = useRef(0)

  const pick = (f) => {
    setError(null)
    const problem = checkImage(f)
    if (problem) { setError(problem); return }
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setFile(f)
    setPreviewUrl(URL.createObjectURL(f))
  }

  const run = async (fn) => {
    lastRun.current = fn
    setBusy(true)
    setError(null)
    setErrorCode(null)
    setNeedsText(false)
    try {
      setResult(await fn())
    } catch (e) {
      setError(errorMessage(e))
      setErrorCode(e?.response?.data?.error?.code || null)
      setNeedsText(e?.response?.data?.error?.code === 'needs_manual_text')
    } finally {
      setBusy(false)
    }
  }

  const reset = () => { setResult(null); setError(null) }

  if (result)
    return (
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-2"><h1 className="text-2xl font-semibold">Review what we found</h1><span className="text-sm text-soft">Step 2 of 2</span></div>
        <div className="mt-5"><ExtractionPreview result={result} original={{ tab, previewUrl, fileName: file?.name, url: url.trim(), text: text.trim() }} onReset={reset} onSaved={(s) => { const n = s.added ?? s.record_count; toast(s.added !== undefined ? `Added ${n} record${n === 1 ? '' : 's'} to “${s.name}”` : `Saved “${s.name}” with ${n} record${n === 1 ? '' : 's'}`); nav(`/sheets/${s.id}`) }} /></div>
      </div>
    )

  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-semibold max-lg:sr-only">Add information</h1>
      <p className="mt-1 text-soft">Add a screenshot, a link or a short description. You review the result before anything is saved.</p>
      <div className="mt-4"><AiStatusBanner /></div>

      <div role="tablist" aria-label="Input method" className="mt-4 flex gap-6 border-b border-line">
        {TABS.map(({ id, label }) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => { setTab(id); setError(null); setNeedsText(false) }}
            className={`-mb-px border-b-2 py-2 text-sm font-medium transition ${tab === id ? 'border-ink text-ink' : 'border-transparent text-soft hover:text-ink'}`}>
            {label}
          </button>
        ))}
      </div>

      <div className="mt-5" role="tabpanel">
        {tab === 'image' && (
          <>
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)}
              onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0]) }}
              onClick={() => fileRef.current?.click()} role="button" tabIndex={0} aria-label="Upload an image"
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && fileRef.current?.click()}
              className={`grid cursor-pointer place-items-center rounded-md border border-dashed px-6 py-10 text-center transition ${dragging ? 'border-brand bg-brand/5' : 'border-line hover:border-brand/60'}`}
            >
              {previewUrl ? (
                <div><img src={previewUrl} alt="Selected screenshot preview" className="mx-auto max-h-56 rounded-md" /><p className="mt-2 text-sm text-soft">{file.name} · click or drop to replace</p></div>
              ) : (
                <div><UploadCloud className="mx-auto h-6 w-6 text-soft" /><p className="mt-2 font-medium">Drop a screenshot here, or click to browse</p><p className="text-sm text-soft">JPG, PNG or WEBP, up to 5 MB</p></div>
              )}
              <input ref={fileRef} type="file" accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
            </div>
            <button className="btn-primary mt-4" disabled={!file || busy} onClick={() => run(() => extractImage(file))}>Extract information</button>
          </>
        )}

        {tab === 'url' && (
          <form onSubmit={(e) => { e.preventDefault(); if (url.trim()) run(() => extractUrl(url.trim())) }}>
            <label htmlFor="url" className="mb-1 block text-sm font-medium">Link to a job, internship or any public page</label>
            <input id="url" className={inputCls} type="url" inputMode="url" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} maxLength={2048} />
            <p className="mt-2 text-xs text-soft">Only public pages are read. DataNest never logs in for you or bypasses sign-in walls.</p>
            <button className="btn-primary mt-4" disabled={!url.trim() || busy}>Extract information</button>
          </form>
        )}

        {tab === 'text' && (
          <>
            <label htmlFor="text" className="mb-1 block text-sm font-medium">Describe it in your own words</label>
            <textarea id="text" className={`${inputCls} min-h-[10rem]`} value={text} maxLength={20000} onChange={(e) => setText(e.target.value)} placeholder="e.g. I spent 500 rupees on internet recharge on 20 November." />
            {pageSourceUrl && <p className="mt-2 text-xs text-soft">Source link kept: {pageSourceUrl}</p>}
            <div className="mt-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
              <button type="button" className="py-2 text-sm text-soft underline hover:text-ink" onClick={() => { setText(EXAMPLES[exampleIdx.current % EXAMPLES.length]); exampleIdx.current += 1 }}>Try an example</button>
              <button className="btn-primary" disabled={text.trim().length < 3 || busy} onClick={() => run(() => extractText(text.trim(), pageSourceUrl))}>Extract information</button>
            </div>
          </>
        )}

        {busy && <p role="status" className="mt-4 flex items-center gap-2 text-sm text-soft"><Loader2 className="h-4 w-4 animate-spin" />Reading your input… {elapsed}s{elapsed >= 10 ? ' (the AI is slower than usual right now, still working)' : ''}</p>}
        {error && (
          <div role="alert" className="mt-4 rounded-md bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-300">
            {error}
            {errorCode?.startsWith('ai_') && errorCode !== 'ai_not_configured' && errorCode !== 'ai_rejected' && lastRun.current && (
              <button className="btn-ghost mt-3 block" onClick={() => run(lastRun.current)} disabled={busy}>Try again</button>
            )}
            {needsText && tab === 'url' && (
              <button className="btn-ghost mt-3 block" onClick={() => { setPageSourceUrl(url.trim()); setTab('text'); setError(null); setNeedsText(false) }}>Paste the page text instead</button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
