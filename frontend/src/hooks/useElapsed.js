import { useEffect, useState } from 'react'

/** Whole seconds since `active` became true (0 when inactive). Lets the UI show that a slow AI call is still working. */
export function useElapsed(active) {
  const [s, setS] = useState(0)
  useEffect(() => {
    if (!active) { setS(0); return }
    const start = Date.now()
    const t = setInterval(() => setS(Math.floor((Date.now() - start) / 1000)), 1000)
    return () => clearInterval(t)
  }, [active])
  return s
}
