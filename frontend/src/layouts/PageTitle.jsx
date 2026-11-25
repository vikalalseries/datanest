import { createContext, useContext, useEffect } from 'react'

export const PageTitleContext = createContext(() => {})

/** Lets a page put its own title (for example a sheet's name) in the mobile header. */
export function usePageTitle(title) {
  const set = useContext(PageTitleContext)
  useEffect(() => {
    set(title || null)
    return () => set(null)
  }, [title, set])
}
