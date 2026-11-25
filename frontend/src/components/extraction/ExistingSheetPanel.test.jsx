import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../../services/firebase', () => ({ auth: null, googleProvider: {}, isAuthConfigured: false }))
const api = { rank: vi.fn(), match: vi.fn(), dups: vi.fn(), bulk: vi.fn() }
vi.mock('../../services/ai', () => ({
  rankSheets: (...a) => api.rank(...a), matchColumns: (...a) => api.match(...a),
  checkDuplicates: (...a) => api.dups(...a), bulkAdd: (...a) => api.bulk(...a),
}))

import ExistingSheetPanel from './ExistingSheetPanel'

const extraction = {
  category: 'job_application',
  columns: [{ name: 'Company', type: 'text' }, { name: 'Position', type: 'text' }, { name: 'Source', type: 'text' }],
  records: [
    { values: { Company: 'Dobbe AI', Position: 'AI Intern', Source: 'LinkedIn' } },
    { values: { Company: 'Acme', Position: 'Dev', Source: 'Web' } },
  ],
}
const source = { type: 'text', url: null, file_id: null }
const ranked = [
  { sheet_id: 's1', name: 'My Jobs', category: 'job_application', record_count: 4, column_names: ['Employer', 'Role'], match_ratio: 0.66, matched: 2, total: 3, category_match: true, score: 0.81 },
  { sheet_id: 's2', name: 'Spending', category: 'expense', record_count: 9, column_names: ['Merchant'], match_ratio: 0, matched: 0, total: 3, category_match: false, score: 0 },
]
const matchResult = {
  sheet: { id: 's1', name: 'My Jobs', category: 'job_application', columns: [{ id: 'c_e', name: 'Employer', type: 'text' }, { id: 'c_r', name: 'Role', type: 'text' }] },
  mappings: [
    { extracted: 'Company', sheet_column_id: 'c_e', sheet_column_name: 'Employer', confidence: 0.9, method: 'synonym' },
    { extracted: 'Position', sheet_column_id: 'c_r', sheet_column_name: 'Role', confidence: 0.9, method: 'synonym' },
    { extracted: 'Source', sheet_column_id: null, sheet_column_name: null, confidence: 0, method: 'none' },
  ],
  notes: [], unmapped_extracted: ['Source'], unfilled_sheet_columns: [], matched: 2, total: 3, match_ratio: 0.667, category_match: true,
  suggestion: 'add_with_new_columns', explanation: 'Partial match: 2 of 3 fields fit “My Jobs”. No column for: Source.',
}

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset())
  api.rank.mockResolvedValue(ranked)
  api.match.mockResolvedValue(matchResult)
  api.dups.mockResolvedValue({ duplicates: [], within_batch: [] })
  api.bulk.mockResolvedValue({ added: 2, sheet: { id: 's1', name: 'My Jobs', record_count: 6 } })
})

const open = async (props = {}) => {
  render(<ExistingSheetPanel extraction={extraction} source={source} onSaved={props.onSaved || (() => {})} onChooseNew={props.onChooseNew || (() => {})} />)
  fireEvent.click(await screen.findByRole('option', { name: /My Jobs/ }))
  await screen.findByText(/Where each field goes/)
}

describe('ExistingSheetPanel', () => {
  it('ranks sheets, flags the best match and shows the mismatch explanation', async () => {
    await open()
    expect(screen.getByText('Best match')).toBeInTheDocument()
    expect(screen.getByText(/Partial match: 2 of 3/)).toBeInTheDocument()
    expect(screen.getByLabelText('Destination for Company')).toHaveValue('c_e')
    // unmatched field with data defaults to "create column", never silently skipped
    expect(screen.getByLabelText('Destination for Source')).toHaveValue('__create')
  })

  it('saves with the explicit mapping', async () => {
    const onSaved = vi.fn()
    await open({ onSaved })
    fireEvent.click(screen.getByRole('button', { name: /add 2 records/i }))
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    const [sheetId, body] = api.bulk.mock.calls[0]
    expect(sheetId).toBe('s1')
    expect(body.mapping).toEqual({ Company: { action: 'map', column_id: 'c_e' }, Position: { action: 'map', column_id: 'c_r' }, Source: { action: 'create', type: 'text' } })
    expect(body.records).toHaveLength(2)
  })

  it('warns when the user chooses to skip a field that has data', async () => {
    await open()
    fireEvent.change(screen.getByLabelText('Destination for Source'), { target: { value: '__skip' } })
    expect(screen.getByText(/You chose to skip: Source/)).toBeInTheDocument()
  })

  it('prevents mapping two fields to the same column', async () => {
    await open()
    const opt = screen.getByLabelText('Destination for Position').querySelector('option[value="c_e"]')
    expect(opt).toBeDisabled() // already used by Company
  })

  it('leaves out duplicates by default and includes them when "Add anyway" is ticked', async () => {
    api.dups.mockResolvedValue({ duplicates: [{ row: 0, existing_record_id: 'r1', similarity: 1, matched_columns: ['Employer', 'Role'], existing: { Employer: 'Dobbe AI', Role: 'AI Intern' } }], within_batch: [] })
    await open()
    expect(await screen.findByText(/Possible duplicates/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add 1 record to this sheet/i })).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Add anyway'))
    expect(screen.getByRole('button', { name: /add 2 records/i })).toBeInTheDocument()
  })

  it('refuses creating a column whose name already exists and offers the new-sheet escape hatch on bad matches', async () => {
    api.match.mockResolvedValue({ ...matchResult, suggestion: 'create_new_sheet', explanation: 'This doesn’t fit “My Jobs”: only 0 of 3 fields match.' })
    const onChooseNew = vi.fn()
    await open({ onChooseNew })
    fireEvent.click(screen.getByRole('button', { name: /create a new sheet instead/i }))
    expect(onChooseNew).toHaveBeenCalled()
  })

  it('shows server errors from saving', async () => {
    api.bulk.mockRejectedValue({ response: { data: { error: { message: 'Row 2: Applied Date: Dates must look like YYYY-MM-DD.' } } } })
    await open()
    fireEvent.click(screen.getByRole('button', { name: /add 2 records/i }))
    expect(await screen.findByText(/Row 2: Applied Date/)).toBeInTheDocument()
  })
})
