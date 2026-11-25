import { api } from './api'

const d = (p) => p.then((r) => r.data)

export const listSheets = (q) => d(api.get('/sheets', { params: q ? { q } : {} }))
export const createSheet = (body) => d(api.post('/sheets', body))
export const getSheet = (id) => d(api.get(`/sheets/${id}`))
export const updateSheet = (id, body) => d(api.put(`/sheets/${id}`, body))
export const trashSheet = (id) => api.delete(`/sheets/${id}`)
export const restoreSheet = (id) => d(api.post(`/sheets/${id}/restore`))
export const purgeSheet = (id) => api.delete(`/sheets/${id}/permanent`)
export const duplicateSheet = (id) => d(api.post(`/sheets/${id}/duplicate`))

export const addColumn = (id, body) => d(api.post(`/sheets/${id}/columns`, body))
export const updateColumn = (id, colId, body) => d(api.patch(`/sheets/${id}/columns/${colId}`, body))
export const deleteColumn = (id, colId) => d(api.delete(`/sheets/${id}/columns/${colId}`))

export const listRecords = (id, params) => d(api.get(`/sheets/${id}/records`, { params }))
export const createRecord = (id, data = {}) => d(api.post(`/sheets/${id}/records`, { data }))
export const updateRecord = (rid, data) => d(api.put(`/records/${rid}`, { data }))
export const bulkDelete = (ids) => d(api.post('/records/bulk-delete', { ids }))
export const restoreRecords = (ids) => d(api.post('/records/restore', { ids }))
export const purgeRecords = (ids) => d(api.post('/records/purge', { ids }))
export const moveRecords = (ids, target_sheet_id, add_missing_columns = false) =>
  d(api.post('/records/move', { ids, target_sheet_id, add_missing_columns }))
export const allRecords = (params) => d(api.get('/records', { params }))

export const getStats = () => d(api.get('/dashboard/stats'))
export const getTrash = () => d(api.get('/trash'))

/** Error helpers: backend sends { error: { code, message, ...extra } } */
export const errCode = (e) => e?.response?.data?.error?.code
