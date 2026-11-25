import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { X, CheckCircle2, AlertCircle } from 'lucide-react'

export function Modal({ title, onClose, children, footer, wide = false }) {
  const ref = useRef(null)
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    ref.current?.querySelector('input,select,textarea,button')?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} className={`card w-full ${wide ? 'max-w-2xl' : 'max-w-md'} max-h-[90vh] overflow-auto`}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 className="font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="text-soft hover:text-ink"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>
  )
}

export function Confirm({ title, message, confirmLabel = 'Confirm', danger = false, onConfirm, onClose }) {
  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className={danger ? 'btn bg-red-600 text-white hover:bg-red-700' : 'btn-primary'} onClick={() => { onConfirm(); onClose() }}>{confirmLabel}</button>
        </>
      }
    >
      <p className="text-sm text-soft">{message}</p>
    </Modal>
  )
}

export const Field = ({ label, children }) => (
  <label className="mb-3 block text-sm">
    <span className="mb-1 block font-medium">{label}</span>
    {children}
  </label>
)

export const inputCls = 'w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand'

const ToastCtx = createContext(() => {})
export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const push = useCallback((message, kind = 'success') => {
    const id = Math.random()
    setItems((x) => [...x, { id, message, kind }])
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 4500)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-24 right-4 z-[60] space-y-2 lg:bottom-4" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="card flex max-w-sm items-start gap-2 px-4 py-3 text-sm">
            {t.kind === 'error' ? <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" /> : <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />}
            {t.message}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

export function Empty({ icon: Icon, title, text, action }) {
  return (
    <div className="card grid place-items-center px-6 py-14 text-center">
      {Icon && <Icon className="h-8 w-8 text-soft" />}
      <p className="mt-3 font-medium">{title}</p>
      {text && <p className="mt-1 max-w-sm text-sm text-soft">{text}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export const COLUMN_TYPES = [
  ['text', 'Text'], ['number', 'Number'], ['currency', 'Currency'], ['date', 'Date'], ['boolean', 'Yes / No'],
  ['email', 'Email'], ['url', 'Link'], ['status', 'Status'], ['tags', 'Tags'],
]
