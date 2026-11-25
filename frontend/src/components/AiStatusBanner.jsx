import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { getAiStatus } from '../services/ai'

const wait = (s) => (s >= 5400 ? `about ${Math.round(s / 3600)} hours` : s >= 90 ? `about ${Math.round(s / 60)} minutes` : 'a minute')

/** Warns BEFORE you wait: shown only when no AI model is currently usable. Costs no AI quota to check. */
export default function AiStatusBanner() {
  const [st, setSt] = useState(null)
  useEffect(() => {
    let cancelled = false
    const load = () => getAiStatus().then((s) => !cancelled && setSt(s)).catch(() => {})
    load()
    const t = setInterval(load, 60000)
    return () => { cancelled = true; clearInterval(t) }
  }, [])
  if (!st || !st.configured || st.any_available) return null
  const quota = st.models.filter((m) => m.state === 'quota')
  const allQuota = quota.length === st.models.length
  const soonest = quota.length ? Math.min(...quota.map((m) => m.resets_in_seconds || 0)) : 0
  return (
    <div role="status" className="mb-4 flex gap-2 rounded-md bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-200">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <p>
        {allQuota
          ? <>AI is out of free quota right now{soonest ? <> (resets in {wait(soonest)})</> : null}. You can still add and edit records by hand; AI features will work again after the reset, or when billing is enabled on the Gemini key.</>
          : <>The AI models are busy or out of quota at the moment, so AI features may fail or be slow. Trying again in a minute usually works.</>}
      </p>
    </div>
  )
}
