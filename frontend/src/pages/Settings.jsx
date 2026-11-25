import { useState } from 'react'
import { useTheme } from '../hooks/useTheme'
import { useToast } from '../components/ui'
import { exportWorkspace } from '../services/files'
import { errorMessage } from '../services/api'

export default function Settings() {
  const { dark, toggle } = useTheme()
  const toast = useToast()
  const [exporting, setExporting] = useState(false)
  const exportAll = async () => {
    setExporting(true)
    try { await exportWorkspace(); toast('Workbook downloaded') } catch (e) { toast(errorMessage(e), 'error') } finally { setExporting(false) }
  }
  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-semibold max-lg:sr-only">Settings</h1>
      <div className="card mt-6 divide-y divide-line">
        <div className="flex items-center justify-between gap-4 p-4 sm:p-5">
          <div>
            <p className="font-medium">Dark theme</p>
            <p className="text-sm text-soft">Saved on this device.</p>
          </div>
          <button role="switch" aria-checked={dark} aria-label="Dark theme" onClick={toggle} className={`h-6 w-11 shrink-0 rounded-full transition ${dark ? 'bg-brand' : 'bg-line'}`}>
            <span className={`block h-5 w-5 rounded-full bg-white transition ${dark ? 'translate-x-5' : 'translate-x-0.5'}`} />
          </button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-4 p-4 sm:p-5">
          <div>
            <p className="font-medium">Export everything</p>
            <p className="text-sm text-soft">One Excel workbook with a worksheet for each sheet.</p>
          </div>
          <button className="btn-ghost" onClick={exportAll} disabled={exporting}>{exporting ? 'Preparing…' : 'Export all (.xlsx)'}</button>
        </div>
      </div>
    </div>
  )
}
