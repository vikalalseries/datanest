import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../services/firebase', () => ({ auth: null, googleProvider: {}, isAuthConfigured: false }))
const api = { status: vi.fn(), text: vi.fn() }
vi.mock('../services/ai', async (orig) => ({ ...(await orig()), getAiStatus: (...a) => api.status(...a), extractText: (...a) => api.text(...a) }))

import AiStatusBanner from './AiStatusBanner'
import SmartAdd from '../pages/SmartAdd'
import { ToastProvider } from './ui'

beforeEach(() => { api.status.mockReset(); api.text.mockReset() })

const st = (models, over = {}) => ({ configured: true, any_available: models.some((m) => m.state === 'ok'), models, ...over })

describe('AiStatusBanner', () => {
  it('stays hidden when at least one model works, or AI is not configured, or the check fails', async () => {
    api.status.mockResolvedValue(st([{ name: 'a', state: 'ok' }, { name: 'b', state: 'quota', resets_in_seconds: 100 }]))
    const { container, rerender } = render(<AiStatusBanner />)
    await waitFor(() => expect(api.status).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
    api.status.mockResolvedValue(st([], { configured: false, any_available: false }))
    rerender(<AiStatusBanner key="x" />)
    await waitFor(() => expect(api.status).toHaveBeenCalledTimes(2))
    expect(container).toBeEmptyDOMElement()
    api.status.mockRejectedValue(new Error('offline'))
    rerender(<AiStatusBanner key="y" />)
    await waitFor(() => expect(api.status).toHaveBeenCalledTimes(3))
    expect(container).toBeEmptyDOMElement()
  })

  it('explains daily quota exhaustion with the reset time and what still works', async () => {
    api.status.mockResolvedValue(st([{ name: 'a', state: 'quota', resets_in_seconds: 45000, daily: true }, { name: 'b', state: 'quota', resets_in_seconds: 46000, daily: true }]))
    render(<AiStatusBanner />)
    const note = await screen.findByRole('status')
    expect(note).toHaveTextContent(/out of free quota/i)
    expect(note).toHaveTextContent(/resets in about 13 hours/)
    expect(note).toHaveTextContent(/by hand/)
  })

  it('says models are busy when none is usable but not all are out of quota', async () => {
    api.status.mockResolvedValue(st([{ name: 'a', state: 'busy', retry_in_seconds: 10 }, { name: 'b', state: 'quota', resets_in_seconds: 500 }]))
    render(<AiStatusBanner />)
    expect(await screen.findByRole('status')).toHaveTextContent(/busy or out of quota/i)
  })
})

describe('SmartAdd error handling', () => {
  const renderPage = () => render(<MemoryRouter><ToastProvider><SmartAdd /></ToastProvider></MemoryRouter>)
  const result = {
    category: 'expense', suggested_sheet_name: 'Expenses', description: '', confidence: 0.9, columns: [{ name: 'Item', type: 'text' }],
    records: [{ values: { Item: 'Internet' }, meta: {} }], missing_fields: [], warnings: [], source: { type: 'text', url: null, file_id: null },
  }

  it('offers Try again after an AI outage and re-runs the same request', async () => {
    api.status.mockResolvedValue(st([{ name: 'a', state: 'ok' }]))
    api.text.mockRejectedValueOnce({ response: { data: { error: { code: 'ai_unavailable', message: 'The AI service is very busy right now.' } } } })
    api.text.mockResolvedValueOnce(result)
    renderPage()
    fireEvent.change(screen.getByLabelText('Describe it in your own words'), { target: { value: 'I spent 500 rupees on internet' } })
    fireEvent.click(screen.getByRole('button', { name: 'Extract information' }))
    expect(await screen.findByText(/very busy right now/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(api.text).toHaveBeenCalledTimes(2))
    expect(api.text.mock.calls[1][0]).toBe('I spent 500 rupees on internet')
    expect(await screen.findByText('Review what we found')).toBeInTheDocument()
  })

  it('does not offer Try again for errors a retry cannot fix', async () => {
    api.status.mockResolvedValue(st([{ name: 'a', state: 'ok' }]))
    api.text.mockRejectedValue({ response: { data: { error: { code: 'nothing_found', message: 'We couldn’t find any information.' } } } })
    renderPage()
    fireEvent.change(screen.getByLabelText('Describe it in your own words'), { target: { value: 'asdf qwer zxcv' } })
    fireEvent.click(screen.getByRole('button', { name: 'Extract information' }))
    expect(await screen.findByText(/couldn’t find any information/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
  })
})
