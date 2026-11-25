import { render, screen } from '@testing-library/react'
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
