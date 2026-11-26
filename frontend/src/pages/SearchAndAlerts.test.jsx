import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../services/firebase', () => ({ auth: null, googleProvider: {}, isAuthConfigured: false }))
const api = { search: vi.fn(), facets: vi.fn(), notes: vi.fn() }
vi.mock('../services/insights', async (orig) => ({ ...(await orig()), searchAll: (...a) => api.search(...a), searchFacets: (...a) => api.facets(...a), getNotifications: (...a) => api.notes(...a) }))

import SearchPage from './SearchPage'
import NotificationBell from '../components/NotificationBell'
import { AppLayout } from '../layouts/AppLayout'
import { AuthProvider } from '../context/AuthContext'

const result = {
  query: 'acme', total: 2, limit: 30, offset: 0,
  sheets: [{ id: 's1', name: 'Acme Tracker', category: 'job_application', record_count: 4 }],
  records: [
    { id: 'r1', sheet_id: 's1', sheet_name: 'Acme Tracker', category: 'job_application', data: { Company: 'Acme', Status: 'Applied' }, updated_at: '2026-11-24T10:00:00Z' },
    { id: 'r2', sheet_id: 's2', sheet_name: 'Spending', category: 'expense', data: { Item: 'Acme lunch', Tags: ['food', 'work'] }, updated_at: '2026-11-23T10:00:00Z' },
  ],
}
const facets = { categories: [{ value: 'job_application', count: 2 }, { value: 'expense', count: 1 }], statuses: [{ value: 'applied', count: 3 }] }

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset())
  api.search.mockResolvedValue(result); api.facets.mockResolvedValue(facets); api.notes.mockResolvedValue({ items: [], count: 0, total: 0 })
  localStorage.clear()
})

const renderSearch = (url = '/search') => render(<MemoryRouter initialEntries={[url]}><Routes><Route path="/search" element={<SearchPage />} /></Routes></MemoryRouter>)

describe('SearchPage', () => {
  it('asks for input before searching and does not call the API with nothing', async () => {
    renderSearch()
    expect(await screen.findByText('Search all your sheets')).toBeInTheDocument()
    expect(api.search).not.toHaveBeenCalled()
  })

  it('searches from the URL and shows sheets and records', async () => {
    renderSearch('/search?q=acme')
    expect(await screen.findByText('Acme Tracker', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getByText('Acme lunch')).toBeInTheDocument()
    expect(screen.getByText('food, work')).toBeInTheDocument()
    expect(screen.getByText(/Records \(2\)/)).toBeInTheDocument()
    expect(api.search.mock.calls[0][0]).toMatchObject({ q: 'acme', limit: 30, offset: 0 })
  })

  it('applies category, status and date filters', async () => {
    renderSearch('/search?q=acme')
    await screen.findByText('Acme lunch')
    fireEvent.change(screen.getByLabelText('Category'), { target: { value: 'expense' } })
    await waitFor(() => expect(api.search).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'acme', category: 'expense' })))
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'applied' } })
    fireEvent.change(screen.getByLabelText('Date from'), { target: { value: '2026-03-01' } })
    fireEvent.change(screen.getByLabelText('Date to'), { target: { value: '2026-03-31' } })
    await waitFor(() => expect(api.search).toHaveBeenLastCalledWith(expect.objectContaining({ category: 'expense', status: 'applied', date_from: '2026-03-01', date_to: '2026-03-31' })))
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(api.search).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'acme', category: undefined, status: undefined })))
  })

  it('works with filters only, and explains empty results', async () => {
    api.search.mockResolvedValue({ query: '', total: 0, limit: 30, offset: 0, sheets: [], records: [] })
    renderSearch('/search?category=expense')
    expect(await screen.findByText('No records match')).toBeInTheDocument()
  })

  it('shows server errors', async () => {
    api.search.mockRejectedValue({ response: { data: { error: { message: 'The “From” date must be before the “To” date.' } } } })
    renderSearch('/search?q=a&from=2026-05-01&to=2026-01-01')
    expect(await screen.findByRole('alert')).toHaveTextContent(/must be before/)
  })
})

describe('Header search', () => {
  function Where() { const l = useLocation(); return <p data-testid="loc">{l.pathname + l.search}</p> }
  it('submitting the header search opens the results page for that query', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <AuthProvider>
          <Routes><Route element={<AppLayout />}><Route path="*" element={<Where />} /></Route></Routes>
        </AuthProvider>
      </MemoryRouter>,
    )
    const box = screen.getByRole('textbox', { name: 'Search everything' })
    fireEvent.change(box, { target: { value: 'dobbe & co' } })
    fireEvent.submit(box.closest('form'))
    expect(screen.getByTestId('loc')).toHaveTextContent('/search?q=dobbe%20%26%20co')
  })
})

const NOTES = [
  { id: 'n1', kind: 'overdue', severity: 'danger', title: 'Late LLC: deadline passed 4 days ago', detail: 'Jobs · 2026-11-20', sheet_id: 's1', sheet_name: 'Jobs', date: '2026-11-20', days: -4 },
  { id: 'n2', kind: 'due_soon', severity: 'warning', title: 'Soon Inc: deadline in 2 days', detail: 'Jobs · 2026-11-26', sheet_id: 's1', sheet_name: 'Jobs', date: '2026-11-26', days: 2 },
  { id: 'n3', kind: 'no_response', severity: 'info', title: 'No response from Quiet Ltd after 21 days', detail: 'Jobs · applied', sheet_id: 's1', sheet_name: 'Jobs', date: '2026-11-03', days: -21 },
]
const renderBell = () => render(<MemoryRouter><NotificationBell refreshMs={10 ** 9} /></MemoryRouter>)

describe('NotificationBell', () => {
  it('shows a count badge and the alerts when opened', async () => {
    api.notes.mockResolvedValue({ items: NOTES, count: 3, total: 3 })
    renderBell()
    const bell = await screen.findByRole('button', { name: /Notifications, 3 new/ })
    fireEvent.click(bell)
    const panel = screen.getByRole('region', { name: 'Notifications' })
    expect(within(panel).getByText('Late LLC: deadline passed 4 days ago')).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: /Soon Inc/ })).toHaveAttribute('href', '/sheets/s1')
  })

  it('dismissed alerts stay dismissed after a reload (remembered on this device)', async () => {
    api.notes.mockResolvedValue({ items: NOTES, count: 3, total: 3 })
    const { unmount } = renderBell()
    fireEvent.click(await screen.findByRole('button', { name: /Notifications, 3 new/ }))
    fireEvent.click(screen.getByRole('button', { name: /Dismiss: Late LLC/ }))
    expect(screen.queryByText(/Late LLC/)).toBeNull()
    expect(screen.getByRole('button', { name: /Notifications, 2 new/ })).toBeInTheDocument()
    unmount()
    renderBell()
    expect(await screen.findByRole('button', { name: /Notifications, 2 new/ })).toBeInTheDocument()
  })

  it('dismiss all empties the list and shows a friendly message', async () => {
    api.notes.mockResolvedValue({ items: NOTES, count: 3, total: 3 })
    renderBell()
    fireEvent.click(await screen.findByRole('button', { name: /Notifications, 3 new/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss all' }))
    expect(screen.getByText(/all caught up/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Notifications' })).toBeInTheDocument()
  })

  it('welcomes each user until they dismiss the message', async () => {
    const bellFor = (id) => render(<MemoryRouter><NotificationBell userId={id} refreshMs={10 ** 9} /></MemoryRouter>)
    const first = bellFor('u1')
    fireEvent.click(await screen.findByRole('button', { name: /Notifications, 1 new/ }))
    expect(screen.getByRole('link', { name: /Welcome to DataNest/ })).toHaveAttribute('href', '/about')
    fireEvent.click(screen.getByRole('button', { name: /Dismiss: Welcome/ }))
    first.unmount()
    const again = bellFor('u1')
    expect(await screen.findByRole('button', { name: 'Notifications' })).toBeInTheDocument()
    again.unmount()
    bellFor('u2')
    expect(await screen.findByRole('button', { name: /Notifications, 1 new/ })).toBeInTheDocument()
  })

  it('does not break the app when notifications cannot be loaded', async () => {
    api.notes.mockRejectedValue(new Error('offline'))
    renderBell()
    fireEvent.click(await screen.findByRole('button', { name: 'Notifications' }))
    expect(await screen.findByText(/Couldn't check for updates/)).toBeInTheDocument()
  })
})
