import { useCallback, useState } from 'react'

const KEY = 'datanest-theme'

export function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  const toggle = useCallback(() => {
    setDark((d) => {
      const next = !d
      document.documentElement.classList.toggle('dark', next)
      try {
        localStorage.setItem(KEY, next ? 'dark' : 'light')
      } catch {
        /* storage unavailable: theme still applies for this session */
      }
      return next
    })
  }, [])
  return { dark, toggle }
}
