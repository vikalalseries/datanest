import { api } from './api'

const AI_TIMEOUT = 120000 // Gemini + retries can take a while
const d = (p) => p.then((r) => r.data)

export const extractText = (text, source_url) => d(api.post('/ai/extract/text', { text, source_url: source_url || null }, { timeout: AI_TIMEOUT }))
export const extractUrl = (url) => d(api.post('/ai/extract/url', { url }, { timeout: AI_TIMEOUT }))
export const extractImage = (file) => {
  const form = new FormData()
  form.append('file', file)
  return d(api.post('/ai/extract/image', form, { timeout: AI_TIMEOUT }))
}
export const saveFromExtraction = (body) => d(api.post('/sheets/from-extraction', body))

export const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']
export const MAX_IMAGE_MB = 5

/** Returns an error string for an unusable file, else null. Server re-validates everything. */
export function checkImage(file) {
  if (!file) return 'Choose an image first.'
  const ext = file.name.split('.').pop().toLowerCase()
  if (!IMAGE_TYPES.includes(file.type) && !['jpg', 'jpeg', 'png', 'webp'].includes(ext)) return 'Unsupported file type. Please use a JPG, PNG or WEBP image.'
  if (file.size > MAX_IMAGE_MB * 1024 * 1024) return `That image is larger than ${MAX_IMAGE_MB} MB.`
  if (file.size === 0) return 'That file is empty.'
  return null
}

// ---------- Phase 4: where to save ----------
export const rankSheets = (extraction) => d(api.post('/ai/rank-sheets', extraction))
export const matchColumns = (sheet_id, extraction, use_ai = true) => d(api.post('/ai/match-columns', { sheet_id, extraction, use_ai }, { timeout: AI_TIMEOUT }))
export const suggestSheet = (extraction) => d(api.post('/ai/suggest-sheet', extraction))
export const checkDuplicates = (sheetId, body) => d(api.post(`/sheets/${sheetId}/records/check-duplicates`, body))
export const bulkAdd = (sheetId, body) => d(api.post(`/sheets/${sheetId}/records/bulk`, body))
export const mergeSheet = (sheetId, body) => d(api.post(`/sheets/${sheetId}/merge`, body))

export const getAiStatus = () => d(api.get('/ai/status'))
