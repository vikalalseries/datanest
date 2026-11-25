import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../services/firebase', () => ({ auth: null, googleProvider: {}, isAuthConfigured: false }))
const api = { chat: vi.fn(), confirm: vi.fn() }
vi.mock('../services/assistant', async (orig) => ({ ...(await orig()), sendChat: (...a) => api.chat(...a), confirmAction: (...a) => api.confirm(...a) }))

import AssistantPage from './AssistantPage'
import RichText from '../components/assistant/RichText'
import { toHistory } from '../services/assistant'

const proposal = {
  id: 'p1', type: 'add_records', title: 'Add 1 record to “Applications”', sheet_name: 'Applications', columns: ['Company', 'Status'],
  rows: [{ Company: 'Nova Labs', Status: 'Applied' }], payload: { type: 'add_records', sheet_id: 's1', records: [{ values: { Company: 'Nova Labs', Status: 'Applied' } }] },
}
const reply = (over = {}) => ({ reply: 'You have **5** applications.', tables: [], proposals: [], tool_trace: [{ tool: 'aggregate', summary: 'Calculated count in “Applications”' }], ...over })

const renderPage = () => render(<MemoryRouter><AssistantPage /></MemoryRouter>)
const ask = (text) => {
  fireEvent.change(screen.getByLabelText('Message the assistant'), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
}

beforeEach(() => { api.chat.mockReset(); api.confirm.mockReset(); sessionStorage.clear() })

describe('RichText', () => {
  it('renders bold and lists, and never injects HTML', () => {
    const { container } = render(<RichText text={'Total: **12**\n- one\n- two\n<img src=x onerror=alert(1)> <script>alert(1)</script>'} />)
    expect(screen.getByText('12').tagName).toBe('STRONG')
    expect(container.querySelectorAll('li')).toHaveLength(2)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.textContent).toContain('<script>alert(1)</script>') // shown as text
  })
})

describe('AssistantPage', () => {
  it('shows suggestions and sends one when clicked', async () => {
    api.chat.mockResolvedValue(reply())
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'How many applications have I sent?' }))
    expect(await screen.findByText(/applications\./)).toBeInTheDocument()
    expect(api.chat).toHaveBeenCalledWith('How many applications have I sent?', [])
    expect(screen.getByText(/Calculated count/)).toBeInTheDocument()
  })

  it('renders result tables with totals', async () => {
    api.chat.mockResolvedValue(reply({ tables: [{ title: 'Applications', columns: ['Company', 'Salary'], rows: [{ Company: 'Acme', Salary: 100 }], total: 7 }] }))
    renderPage(); ask('show')
    expect(await screen.findByText('Acme')).toBeInTheDocument()
    expect(screen.getByText(/showing 1 of 7/)).toBeInTheDocument()
  })

  it('sends conversation history but not error bubbles', async () => {
    api.chat.mockRejectedValueOnce({ response: { data: { error: { message: 'The AI service is busy.' } } } })
    renderPage(); ask('first')
    expect(await screen.findByRole('alert')).toHaveTextContent('The AI service is busy.')
    api.chat.mockResolvedValueOnce(reply({ reply: 'second answer' }))
    ask('second')
    await screen.findByText('second answer')
    expect(api.chat.mock.calls[1][1]).toEqual([{ role: 'user', text: 'first' }])
  })

  it('never saves a proposal until Confirm is pressed, then links to the sheet', async () => {
    api.chat.mockResolvedValue(reply({ reply: 'I prepared it.', proposals: [proposal] }))
    renderPage(); ask('add nova labs')
    expect(await screen.findByText(/Proposal · not saved yet/)).toBeInTheDocument()
    expect(api.confirm).not.toHaveBeenCalled()
    api.confirm.mockResolvedValue({ type: 'add_records', sheet_id: 's1', sheet_name: 'Applications', added: 1 })
    fireEvent.click(screen.getByRole('button', { name: /add to sheet/i }))
    await waitFor(() => expect(api.confirm).toHaveBeenCalledWith(proposal.payload))
    expect(await screen.findByText(/Added 1 record/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open “Applications”/ })).toHaveAttribute('href', '/sheets/s1')
  })

  it('dismissing a proposal saves nothing; confirm errors are shown and can be retried', async () => {
    api.chat.mockResolvedValue(reply({ proposals: [proposal] }))
    renderPage(); ask('x')
    fireEvent.click(await screen.findByRole('button', { name: /dismiss/i }))
    expect(screen.getByText(/Nothing was saved/)).toBeInTheDocument()
    expect(api.confirm).not.toHaveBeenCalled()
  })

  it('shows the server error from a failed confirmation', async () => {
    api.chat.mockResolvedValue(reply({ proposals: [proposal] }))
    api.confirm.mockRejectedValue({ response: { data: { error: { message: 'This sheet has no column: Foo.' } } } })
    renderPage(); ask('x')
    fireEvent.click(await screen.findByRole('button', { name: /add to sheet/i }))
    expect(await screen.findByText(/no column: Foo/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add to sheet/i })).toBeEnabled()
  })

  it('clears the chat', async () => {
    api.chat.mockResolvedValue(reply())
    renderPage(); ask('hi')
    await screen.findByText(/applications\./)
    fireEvent.click(screen.getByRole('button', { name: /clear chat/i }))
    expect(screen.queryByText(/applications\./)).toBeNull()
  })
})

describe('toHistory', () => {
  it('keeps the last 10 text turns only', () => {
    const msgs = Array.from({ length: 14 }, (_, i) => ({ id: i, role: i % 2 ? 'assistant' : 'user', text: `m${i}` }))
    msgs.push({ id: 99, role: 'assistant', text: 'boom', error: true })
    const h = toHistory(msgs)
    expect(h).toHaveLength(10)
    expect(h.at(-1).text).toBe('m13')
    expect(h.some((x) => x.text === 'boom')).toBe(false)
  })
})
