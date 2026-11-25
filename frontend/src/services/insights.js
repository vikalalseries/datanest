import { api } from './api'

const d = (p) => p.then((r) => r.data)

// templates
export const listTemplates = () => d(api.get('/templates'))
export const instantiateTemplate = (key, name) => d(api.post(`/templates/${key}/instantiate`, { name: name || null }))
export const generateTemplate = (description) => d(api.post('/ai/generate-template', { description }, { timeout: 120000 }))

// analytics
export const getSheetAnalytics = (id) => d(api.get(`/analytics/sheet/${id}`))
export const getOverview = () => d(api.get('/analytics/overview'))

// search
export const searchAll = (params) => d(api.get('/search', { params }))
export const searchFacets = () => d(api.get('/search/facets'))

// activity
export const getActivity = (params) => d(api.get('/activity', { params }))
export const undoActivity = (id) => d(api.post(`/activity/${id}/undo`))

// notifications
export const getNotifications = () => d(api.get('/notifications'))

export const CATEGORIES = [
  ['general', 'General'], ['job_application', 'Job applications'], ['internship_application', 'Internship applications'], ['expense', 'Expenses'],
  ['project_task', 'Project tasks'], ['academic_task', 'Academic'], ['customer', 'Customers'], ['meeting', 'Meetings'], ['personal_task', 'Personal tasks'],
]
export const categoryLabel = (c) => CATEGORIES.find(([v]) => v === c)?.[1] || c.replace(/_/g, ' ')
