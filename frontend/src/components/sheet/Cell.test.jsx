import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { Cell } from './Cell'
import { isComplete } from './FilterPanel'

const text = { id: 'c_1', name: 'Company', type: 'text' }

describe('Cell', () => {
  it('commits an edited value on Enter', () => {
    const onCommit = vi.fn()
    render(<Cell column={text} value="Acme" onCommit={onCommit} />)
    fireEvent.click(screen.getByRole('button', { name: /edit company/i }))
    const input = screen.getByDisplayValue('Acme')
    fireEvent.change(input, { target: { value: 'Globex' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onCommit).toHaveBeenCalledWith('Globex')
  })

  it('does not commit when unchanged or cancelled with Escape', () => {
    const onCommit = vi.fn()
    render(<Cell column={text} value="Acme" onCommit={onCommit} />)
    fireEvent.click(screen.getByRole('button', { name: /edit company/i }))
    fireEvent.keyDown(screen.getByDisplayValue('Acme'), { key: 'Enter' })
    fireEvent.click(screen.getByRole('button', { name: /edit company/i }))
    const input = screen.getByDisplayValue('Acme')
    fireEvent.change(input, { target: { value: 'Other' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(onCommit).not.toHaveBeenCalled()
  })

  it('toggles booleans immediately', () => {
    const onCommit = vi.fn()
    render(<Cell column={{ id: 'c_2', name: 'Paid', type: 'boolean' }} value={false} onCommit={onCommit} />)
    fireEvent.click(screen.getByRole('checkbox'))
    expect(onCommit).toHaveBeenCalledWith(true)
  })

  it('renders tags as chips and links safely', () => {
    render(<Cell column={{ id: 'c_3', name: 'Tags', type: 'tags' }} value={['ai', 'remote']} onCommit={() => {}} />)
    expect(screen.getByText('ai')).toBeInTheDocument()
    render(<Cell column={{ id: 'c_4', name: 'Link', type: 'url' }} value="https://example.com" onCommit={() => {}} />)
    expect(screen.getByRole('link')).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })
})

describe('filters', () => {
  it('only treats complete filters as sendable', () => {
    expect(isComplete({ column: 'c', op: 'contains', value: '' })).toBe(false)
    expect(isComplete({ column: 'c', op: 'contains', value: 'x' })).toBe(true)
    expect(isComplete({ column: 'c', op: 'empty', value: '' })).toBe(true)
  })
})
