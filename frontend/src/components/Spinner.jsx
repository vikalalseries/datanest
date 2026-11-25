import { Loader2 } from 'lucide-react'

export function Spinner({ full = false }) {
  const icon = <Loader2 className="h-6 w-6 animate-spin text-brand" aria-label="Loading" />
  return full ? <div className="flex min-h-screen items-center justify-center">{icon}</div> : icon
}
