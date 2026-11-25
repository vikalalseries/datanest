import { api } from './api'

const d = (p) => p.then((r) => r.data)

function filenameFrom(headers, fallback) {
  const cd = headers?.['content-disposition'] || ''
  const star = /filename\*=UTF-8''([^;]+)/i.exec(cd)
  if (star) {
    try { return decodeURIComponent(star[1]) } catch { /* fall through */ }
  }
  const plain = /filename="?([^";]+)"?/i.exec(cd)
  return plain ? plain[1] : fallback
}

/** Turn a failed blob request into a normal error whose body is parsed JSON (so errorMessage() works). */
async function unblob(error) {
  const data = error?.response?.data
  if (data instanceof Blob) {
    try { error.response.data = JSON.parse(await data.text()) } catch { /* keep generic message */ }
  }
  throw error
}

async function downloadBlob(path, params, fallbackName) {
  let res
  try {
    res = await api.get(path, { params, responseType: 'blob', timeout: 120000 })
  } catch (e) {
    return unblob(e)
  }
  const name = filenameFrom(res.headers, fallbackName)
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10000)
  return { name, truncated: res.headers?.['x-export-truncated'] === 'true' }
}

export const exportSheet = (id, format = 'xlsx') => downloadBlob(`/export/sheet/${id}`, { format }, `sheet.${format}`)
export const exportWorkspace = () => downloadBlob('/export/workspace', undefined, 'datanest-all-sheets.xlsx')

export const previewImport = (file) => {
  const form = new FormData()
  form.append('file', file)
  return d(api.post('/import/preview', form, { timeout: 120000 }))
}
export const commitImport = (file, options) => {
  const form = new FormData()
  form.append('file', file)
  form.append('options', JSON.stringify(options))
  return d(api.post('/import/commit', form, { timeout: 180000 }))
}

export async function openOriginal(fileId) {
  const { url } = await d(api.get(`/files/${fileId}/download`))
  window.open(url, '_blank', 'noopener,noreferrer')
}

export const IMPORT_MAX_MB = 10
export function checkImportFile(file) {
  if (!file) return 'Choose a file first.'
  const ext = file.name.split('.').pop().toLowerCase()
  if (ext === 'xls' || ext === 'xlsm' || ext === 'xlsb') return 'Only .xlsx and .csv files are supported. Open it in Excel and save it as .xlsx first.'
  if (!['xlsx', 'csv'].includes(ext)) return 'Unsupported file type. Please choose an .xlsx or .csv file.'
  if (file.size === 0) return 'That file is empty.'
  if (file.size > IMPORT_MAX_MB * 1024 * 1024) return `That file is larger than ${IMPORT_MAX_MB} MB.`
  return null
}
