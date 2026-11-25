import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../services/firebase', () => ({ auth: null, googleProvider: {}, isAuthConfigured: false }))
const api = { preview: vi.fn(), commit: vi.fn() }
vi.mock('../services/files', async (orig) => ({ ...(await orig()), previewImport: (...a) => api.preview(...a), commitImport: (...a) => api.commit(...a) }))

import ImportPage from './ImportPage'
import { ToastProvider } from '../components/ui'
import { checkImportFile } from '../services/files'

const preview = {
  filename: 'jobs.xlsx',
  worksheets: [
    {
      name: 'Applications', row_count: 2, warnings: ['Duplicate column name “Name” was renamed.'],
      columns: [{ name: 'Company', type: 'text' }, { name: 'Applied', type: 'date' }, { name: 'Salary', type: 'currency', note: undefined }, { name: 'D', type: 'text', note: 'These dates are ambiguous (day/month order), so they are kept as text.' }],
      sample_rows: [['Acme', '2026-11-23', 100, '03/04/2026'], ['Globex', '2026-12-01', 250.5, '05/06/2026']],
    },
    { name: 'Other', row_count: 1, warnings: [], columns: [{ name: 'Name', type: 'text' }], sample_rows: [['Zed']] },
  ],
}
const file = (name = 'jobs.xlsx', size = 100) => new File([new Uint8Array(size)], name)

beforeEach(() => { api.preview.mockReset(); api.commit.mockReset(); api.preview.mockResolvedValue(preview) })

async function upload(f = file()) {
  render(<MemoryRouter><ToastProvider><ImportPage /></ToastProvider></MemoryRouter>)
  const input = document.querySelector('input[type=file]')
  fireEvent.change(input, { target: { files: [f] } })
  await screen.findByText(/2 rows found/)
}

describe('ImportPage', () => {
  it('shows an editable preview with warnings and ambiguity notes', async () => {
    await upload()
    expect(screen.getByDisplayValue('Company')).toBeInTheDocument()
    expect(screen.getByText(/Duplicate column name/)).toBeInTheDocument()
    expect(screen.getByText(/ambiguous/)).toBeInTheDocument()
    expect(screen.getByLabelText('Sheet name')).toHaveValue('jobs - Applications')
    expect(api.commit).not.toHaveBeenCalled() // nothing is saved by previewing
  })

  it('commits the edited names, types and exclusions', async () => {
    api.commit.mockResolvedValue({ id: 's1', name: 'My jobs', record_count: 2 })
    await upload()
    fireEvent.change(screen.getByDisplayValue('Company'), { target: { value: 'Employer' } })
    fireEvent.change(screen.getByLabelText('Type of Salary'), { target: { value: 'number' } })
    fireEvent.click(screen.getByLabelText('Import column D'))
    fireEvent.change(screen.getByLabelText('Sheet name'), { target: { value: 'My jobs' } })
    fireEvent.click(screen.getByRole('button', { name: /import 2 rows/i }))
    await waitFor(() => expect(api.commit).toHaveBeenCalled())
    const [, opts] = api.commit.mock.calls[0]
    expect(opts.sheet_name).toBe('My jobs')
    expect(opts.worksheet).toBe('Applications')
    expect(opts.columns).toEqual([
      { index: 0, name: 'Employer', type: 'text', include: true },
      { index: 1, name: 'Applied', type: 'date', include: true },
      { index: 2, name: 'Salary', type: 'number', include: true },
      { index: 3, name: 'D', type: 'text', include: false },
    ])
  })

  it('switching worksheet reloads the columns', async () => {
    await upload()
    fireEvent.change(screen.getByLabelText('Worksheet'), { target: { value: '1' } })
    expect(await screen.findByDisplayValue('Name')).toBeInTheDocument()
    expect(screen.getByLabelText('Sheet name')).toHaveValue('jobs - Other')
  })

  it('blocks import with duplicate column names', async () => {
    await upload()
    fireEvent.change(screen.getByDisplayValue('Applied'), { target: { value: 'company' } })
    expect(screen.getByRole('button', { name: /import 2 rows/i })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent(/unique name/i)
  })

  it('shows the server message when the import fails and keeps the edits', async () => {
    api.commit.mockRejectedValue({ response: { data: { error: { message: 'Row 3, “Amount”: Not a number.' } } } })
    await upload()
    fireEvent.click(screen.getByRole('button', { name: /import 2 rows/i }))
    expect(await screen.findByText(/Row 3, “Amount”/)).toBeInTheDocument()
    expect(screen.getByDisplayValue('Company')).toBeInTheDocument()
  })

  it('rejects unsupported files before uploading', async () => {
    render(<MemoryRouter><ToastProvider><ImportPage /></ToastProvider></MemoryRouter>)
    fireEvent.change(document.querySelector('input[type=file]'), { target: { files: [file('notes.txt')] } })
    expect(await screen.findByText(/Unsupported file type/)).toBeInTheDocument()
    expect(api.preview).not.toHaveBeenCalled()
  })
})

describe('checkImportFile', () => {
  it('validates type and size', () => {
    expect(checkImportFile(file('a.xlsx'))).toBeNull()
    expect(checkImportFile(file('a.CSV'))).toBeNull()
    expect(checkImportFile(file('a.xls'))).toMatch(/save it as .xlsx/)
    expect(checkImportFile(file('a.xlsm'))).toMatch(/Only .xlsx/)
    expect(checkImportFile(file('a.pdf'))).toMatch(/Unsupported/)
    expect(checkImportFile(file('a.csv', 0))).toMatch(/empty/)
    expect(checkImportFile(file('big.csv', 11 * 1024 * 1024))).toMatch(/larger/)
  })
})
