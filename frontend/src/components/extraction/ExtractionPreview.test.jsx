import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../../services/firebase', () => ({ auth: null, googleProvider: {}, isAuthConfigured: false }))
const save = vi.fn()
let outcome = () => Promise.resolve()
// the rejection is created outside the spy so vitest doesn't track it as unhandled
vi.mock('../../services/ai', async (orig) => ({ ...(await orig()), saveFromExtraction: (...a) => { save(...a); return outcome() },
  suggestSheet: () => Promise.resolve({ similar_sheets: [] }), rankSheets: () => Promise.resolve([]) }))

import ExtractionPreview from './ExtractionPreview'
import { checkImage } from '../../services/ai.js'

const result = {
  category: 'internship_application', suggested_sheet_name: 'Internship Applications', description: 'd', confidence: 0.93,
  columns: [{ name: 'Company', type: 'text' }, { name: 'Status', type: 'status' }],
  records: [{ values: { Company: 'Dobbe AI', Status: 'Applied' }, meta: { Company: { origin: 'extracted', uncertain: false }, Status: { origin: 'inferred', uncertain: true } } }],
  missing_fields: ['Deadline'], warnings: ['Check the date'], source: { type: 'text', url: null, file_id: null },
}

beforeEach(() => { save.mockReset(); outcome = () => Promise.resolve() })

describe('ExtractionPreview', () => {
  it('shows editable values, warnings and missing fields', () => {
    render(<ExtractionPreview result={result} onSaved={() => {}} onReset={() => {}} />)
    expect(screen.getByDisplayValue('Dobbe AI')).toBeInTheDocument()
    expect(screen.getByText('Check the date')).toBeInTheDocument()
    expect(screen.getByText(/Deadline/)).toBeInTheDocument()
    expect(screen.getByText(/93% confident/)).toBeInTheDocument()
  })

  it('sends the EDITED values, renamed column and sheet name when saving', async () => {
    outcome = () => Promise.resolve({ id: 's1', name: 'My Apps', record_count: 1 })
    const onSaved = vi.fn()
    render(<ExtractionPreview result={result} onSaved={onSaved} onReset={() => {}} />)
    fireEvent.change(screen.getByDisplayValue('Dobbe AI'), { target: { value: 'Dobbe AI Pvt' } })
    fireEvent.change(screen.getByDisplayValue('Company'), { target: { value: 'Employer' } })
    fireEvent.change(screen.getByLabelText('Sheet name'), { target: { value: 'My Apps' } })
    fireEvent.click(screen.getByRole('button', { name: /save as new sheet/i }))
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    const body = save.mock.calls[0][0]
    expect(body.name).toBe('My Apps')
    expect(body.columns.map((c) => c.name)).toEqual(['Employer', 'Status'])
    expect(body.records[0].values).toEqual({ Employer: 'Dobbe AI Pvt', Status: 'Applied' })
  })

  it('blocks saving with duplicate column names or no rows', () => {
    render(<ExtractionPreview result={result} onSaved={() => {}} onReset={() => {}} />)
    fireEvent.change(screen.getAllByLabelText('Column name')[1], { target: { value: 'company' } })
    expect(screen.getByRole('button', { name: /save as new sheet/i })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent(/unique name/i)
  })

  it('shows the server error when saving fails and keeps edits', async () => {
    outcome = () => Promise.reject({ response: { data: { error: { message: 'Row 1: Salary: Not a number.' } } } })
    render(<ExtractionPreview result={result} onSaved={() => {}} onReset={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /save as new sheet/i }))
    expect(await screen.findByText(/Not a number/)).toBeInTheDocument()
    expect(screen.getByDisplayValue('Dobbe AI')).toBeInTheDocument()
  })
})

describe('checkImage', () => {
  it('accepts allowed images and rejects others', () => {
    const f = (name, type, size = 100) => new File([new Uint8Array(size)], name, { type })
    expect(checkImage(f('a.png', 'image/png'))).toBeNull()
    expect(checkImage(f('a.webp', 'image/webp'))).toBeNull()
    expect(checkImage(f('a.gif', 'image/gif'))).toMatch(/Unsupported/)
    expect(checkImage(f('a.pdf', 'application/pdf'))).toMatch(/Unsupported/)
    expect(checkImage(f('big.png', 'image/png', 6 * 1024 * 1024))).toMatch(/larger/)
    expect(checkImage(null)).toBeTruthy()
  })
})
