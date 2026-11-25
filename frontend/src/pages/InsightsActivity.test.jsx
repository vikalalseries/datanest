import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../services/firebase', () => ({ auth: null, googleProvider: {}, isAuthConfigured: false }))
const api = { analytics: vi.fn(), activity: vi.fn(), undo: vi.fn() }
vi.mock('../services/insights', async (orig) => ({ ...(await orig()), getSheetAnalytics: (...a) => api.analytics(...a), getActivity: (...a) => api.activity(...a), undoActivity: (...a) => api.undo(...a) }))

import InsightsPanel from '../components/sheet/InsightsPanel'
import ActivityPage from './ActivityPage'
import { ToastProvider } from '../components/ui'

beforeEach(() => Object.values(api).forEach((f) => f.mockReset()))

const JOB = {
  applicable: true, kind: 'job', category: 'job_application', notes: ['1 application(s) have a status that isn’t counted.'],
  metrics: [
    { key: 'applications', label: 'Applications sent', value: 8 }, { key: 'interviews', label: 'Interviews', value: 1 }, { key: 'rejections', label: 'Rejections', value: 1 },
    { key: 'offers', label: 'Offers', value: 1 }, { key: 'pending', label: 'Pending', value: 3 }, { key: 'response_rate', label: 'Response rate', value: 37.5, unit: '%' },
  ],
  breakdown: [{ label: 'Applied', value: 2 }, { label: 'Interview', value: 1 }],
}

describe('InsightsPanel', () => {
  it('shows the job funnel for job sheets', async () => {
    api.analytics.mockResolvedValue(JOB)
    render(<InsightsPanel sheetId="s1" refreshKey={0} />)
    expect(await screen.findByText('Application insights')).toBeInTheDocument()
    expect(screen.getByText('Applications sent').nextSibling).toHaveTextContent('8')
    expect(screen.getByText('Response rate').nextSibling).toHaveTextContent('37.5%')
    expect(screen.getByText('Applied')).toBeInTheDocument()
    expect(screen.getByText(/isn’t counted/)).toBeInTheDocument()
  })

  it('renders NOTHING for categories without meaningful analytics', async () => {
    api.analytics.mockResolvedValue({ applicable: false, kind: null, category: 'general', metrics: [], breakdown: [], notes: [], reason: 'Insights appear for job...' })
    const { container } = render(<InsightsPanel sheetId="s1" refreshKey={0} />)
    await waitFor(() => expect(api.analytics).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByText(/insights/i)).toBeNull()
  })

  it('stays hidden if analytics fail, and refetches when the data changes', async () => {
    api.analytics.mockRejectedValue(new Error('x'))
    const { container, rerender } = render(<InsightsPanel sheetId="s1" refreshKey={0} />)
    await waitFor(() => expect(api.analytics).toHaveBeenCalledTimes(1))
    expect(container).toBeEmptyDOMElement()
    api.analytics.mockResolvedValue(JOB)
    rerender(<InsightsPanel sheetId="s1" refreshKey={1} />)
    expect(await screen.findByText('Application insights')).toBeInTheDocument()
    expect(api.analytics).toHaveBeenCalledTimes(2)
  })

  it('can be collapsed', async () => {
    api.analytics.mockResolvedValue(JOB)
    render(<InsightsPanel sheetId="s1" refreshKey={0} />)
    fireEvent.click(await screen.findByRole('button', { name: /Application insights/ }))
    expect(screen.queryByText('Applications sent')).toBeNull()
  })
})

const ITEMS = [
  { id: 'a1', action: 'record.update', summary: 'Edited a row in “Jobs”', changes: [{ column: 'Status', before: 'Applied', after: 'Interview' }], sheet_id: 's1', sheet_name: 'Jobs', created_at: '2026-11-24T10:00:00Z', undoable: true, undone: false },
  { id: 'a2', action: 'export.sheet', summary: 'Exported “Jobs” as CSV', changes: [], sheet_id: 's1', sheet_name: 'Jobs', created_at: '2026-11-24T09:00:00Z', undoable: false, undone: false },
  { id: 'a3', action: 'record.trash', summary: 'Moved rows to Trash (2)', changes: [], sheet_id: 's1', sheet_name: 'Jobs', created_at: '2026-11-24T08:00:00Z', undoable: false, undone: true },
]
const renderActivity = () => render(<MemoryRouter><ToastProvider><ActivityPage /></ToastProvider></MemoryRouter>)

describe('ActivityPage', () => {
  it('lists readable history with before/after changes and only offers undo where possible', async () => {
    api.activity.mockResolvedValue({ items: ITEMS, total: 3, limit: 30, offset: 0 })
    renderActivity()
    expect(await screen.findByText('Edited a row in “Jobs”')).toBeInTheDocument()
    expect(screen.getByText('Interview')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Undo/ })).toHaveLength(1) // not for the export, not for the already-undone one
    expect(within(screen.getByText('Moved rows to Trash (2)').closest('li')).getByText(/undone/)).toBeInTheDocument()
  })

  it('asks for confirmation, undoes, and reloads', async () => {
    api.activity.mockResolvedValue({ items: ITEMS, total: 3, limit: 30, offset: 0 })
    api.undo.mockResolvedValue({ message: 'Edit undone.' })
    renderActivity()
    fireEvent.click(await screen.findByRole('button', { name: /Undo/ }))
    expect(api.undo).not.toHaveBeenCalled() // nothing happens until confirmed
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(api.undo).toHaveBeenCalledWith('a1'))
    expect(await screen.findByText('Edit undone.')).toBeInTheDocument()
    expect(api.activity).toHaveBeenCalledTimes(2)
  })

  it('shows the refusal when an undo would overwrite newer edits', async () => {
    api.activity.mockResolvedValue({ items: ITEMS, total: 3, limit: 30, offset: 0 })
    api.undo.mockRejectedValue({ response: { data: { error: { message: 'This row was edited again after that change.' } } } })
    renderActivity()
    fireEvent.click(await screen.findByRole('button', { name: /Undo/ }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Undo' }))
    expect(await screen.findByText(/edited again after that change/)).toBeInTheDocument()
  })

  it('loads older entries on demand, and handles an empty history', async () => {
    api.activity.mockResolvedValueOnce({ items: ITEMS.slice(0, 2), total: 3, limit: 30, offset: 0 })
    api.activity.mockResolvedValueOnce({ items: [ITEMS[2]], total: 3, limit: 30, offset: 2 })
    renderActivity()
    fireEvent.click(await screen.findByRole('button', { name: /Show more \(1 older\)/ }))
    await waitFor(() => expect(api.activity).toHaveBeenLastCalledWith({ limit: 30, offset: 2 }))
    expect(await screen.findByText('Moved rows to Trash (2)')).toBeInTheDocument()
  })

  it('empty state', async () => {
    api.activity.mockResolvedValue({ items: [], total: 0, limit: 30, offset: 0 })
    renderActivity()
    expect(await screen.findByText('No activity yet')).toBeInTheDocument()
  })
})
