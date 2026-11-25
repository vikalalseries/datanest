import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../services/firebase', () => ({ auth: null, googleProvider: {}, isAuthConfigured: false }))
const api = { list: vi.fn(), inst: vi.fn(), gen: vi.fn(), create: vi.fn() }
vi.mock('../services/insights', async (orig) => ({ ...(await orig()), listTemplates: (...a) => api.list(...a), instantiateTemplate: (...a) => api.inst(...a), generateTemplate: (...a) => api.gen(...a) }))
vi.mock('../services/sheets', async (orig) => ({ ...(await orig()), createSheet: (...a) => api.create(...a) }))

import Templates from './Templates'
import { ToastProvider } from '../components/ui'

const NAMES = ['Internship Tracker', 'Job Application Tracker', 'Expense Tracker', 'Project Management', 'Student Academic Tracker', 'Customer Management', 'Meeting Records', 'Personal Task Tracker']
const templates = NAMES.map((name, i) => ({ key: `t${i}`, name, icon: 'briefcase', category: 'general', description: `${name} description`, columns: [{ name: 'Company', type: 'text' }, { name: 'Status', type: 'status', options: ['A', 'B'] }] }))

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/templates']}>
      <ToastProvider>
        <Routes>
          <Route path="/templates" element={<Templates />} />
          <Route path="/sheets/:id" element={<p>Sheet page</p>} />
        </Routes>
      </ToastProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => { Object.values(api).forEach((f) => f.mockReset()); api.list.mockResolvedValue(templates) })

describe('Templates gallery', () => {
  it('shows all eight templates', async () => {
    renderPage()
    for (const n of NAMES) expect(await screen.findByText(n)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /^Use / })).toHaveLength(8)
  })

  it('creates a sheet from a template with the chosen name and opens it', async () => {
    api.inst.mockResolvedValue({ id: 's9', name: 'My Internships' })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Use Internship Tracker' }))
    const input = screen.getByLabelText('Sheet name')
    expect(input).toHaveValue('Internship Tracker')
    fireEvent.change(input, { target: { value: 'My Internships' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create sheet' }))
    await waitFor(() => expect(api.inst).toHaveBeenCalledWith('t0', 'My Internships'))
    expect(await screen.findByText('Sheet page')).toBeInTheDocument()
  })

  it('shows an error if the gallery cannot load', async () => {
    api.list.mockRejectedValue({ response: { data: { error: { message: 'Cannot load templates' } } } })
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot load templates')
  })
})

describe('AI template generator', () => {
  const draft = { name: 'Gym Log', description: 'Workouts', category: 'fitness', columns: [{ name: 'Exercise', type: 'text' }, { name: 'Mood', type: 'status', options: ['Great', 'Ok'] }] }

  async function generate() {
    renderPage()
    fireEvent.change(await screen.findByLabelText('Describe the sheet you want'), { target: { value: 'a workout log' } })
    fireEvent.click(screen.getByRole('button', { name: /design my sheet/i }))
    await screen.findByDisplayValue('Gym Log')
  }

  it('previews an editable draft and creates the EDITED sheet', async () => {
    api.gen.mockResolvedValue(draft)
    api.create.mockResolvedValue({ id: 's7' })
    await generate()
    expect(api.create).not.toHaveBeenCalled() // a preview saves nothing
    fireEvent.change(screen.getByDisplayValue('Exercise'), { target: { value: 'Movement' } })
    fireEvent.click(screen.getByRole('button', { name: /remove column mood/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Create sheet' }))
    await waitFor(() => expect(api.create).toHaveBeenCalled())
    expect(api.create.mock.calls[0][0]).toEqual({ name: 'Gym Log', description: 'Workouts', category: 'fitness', columns: [{ name: 'Movement', type: 'text' }] })
    expect(await screen.findByText('Sheet page')).toBeInTheDocument()
  })

  it('keeps status options when creating, and blocks duplicate or empty column names', async () => {
    api.gen.mockResolvedValue(draft)
    api.create.mockResolvedValue({ id: 's8' })
    await generate()
    fireEvent.change(screen.getByLabelText('Column 2 name'), { target: { value: 'exercise' } })
    expect(screen.getByRole('button', { name: 'Create sheet' })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent(/unique name/i)
    fireEvent.change(screen.getByLabelText('Column 2 name'), { target: { value: 'Mood' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create sheet' }))
    await waitFor(() => expect(api.create).toHaveBeenCalled())
    expect(api.create.mock.calls[0][0].columns[1]).toEqual({ name: 'Mood', type: 'status', options: ['Great', 'Ok'] })
  })

  it('shows AI errors in plain words', async () => {
    api.gen.mockRejectedValue({ response: { data: { error: { message: 'The AI service is busy.' } } } })
    renderPage()
    fireEvent.change(await screen.findByLabelText('Describe the sheet you want'), { target: { value: 'something' } })
    fireEvent.click(screen.getByRole('button', { name: /design my sheet/i }))
    expect(await screen.findByText('The AI service is busy.')).toBeInTheDocument()
  })
})
