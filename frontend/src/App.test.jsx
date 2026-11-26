import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'

vi.mock('./services/firebase', () => ({ auth: null, googleProvider: {}, isAuthConfigured: false }))

import App from './App'
import { AuthProvider } from './context/AuthContext'

const renderAt = (path) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )

describe('routing', () => {
  it('shows the landing page publicly', () => {
    renderAt('/')
    expect(screen.getByText(/Give it information/i)).toBeInTheDocument()
  })

  it('lets visitors open the About page from the landing page without signing in', async () => {
    renderAt('/')
    fireEvent.click(screen.getByRole('link', { name: 'About DataNest' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'About DataNest' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
    expect(screen.getByRole('link', { name: 'Get started' })).toHaveAttribute('href', '/login')
    expect(screen.queryByRole('link', { name: 'Sheets' })).toBeNull()
  })

  it('redirects protected routes to login when unauthenticated', () => {
    renderAt('/dashboard')
    expect(screen.getByText(/Welcome to DataNest/i)).toBeInTheDocument()
  })

  it('warns when Firebase is not configured and disables sign-in', () => {
    renderAt('/login')
    expect(screen.getByRole('alert')).toHaveTextContent(/not configured/i)
    expect(screen.getByRole('button', { name: /continue with google/i })).toBeDisabled()
  })
})
