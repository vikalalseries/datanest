import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { AlertCircle } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { Spinner } from '../components/Spinner'

export default function Login() {
  const { session, loading, configured, signInWithGoogle } = useAuth()
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  if (loading) return <Spinner full />
  if (session) return <Navigate to="/dashboard" replace />

  const onClick = async () => {
    setBusy(true)
    setError(null)
    const { error: err } = await signInWithGoogle()
    if (err) setError(err)
    setBusy(false)
  }

  return (
    <div className="grid min-h-screen place-items-center p-4">
      <div className="card w-full max-w-sm p-8 text-center">
        <p className="text-2xl font-bold tracking-tight">DataNest</p>
        <h1 className="mt-2 text-2xl font-semibold">Welcome to DataNest</h1>
        <p className="mt-1 text-sm text-soft">Sign in to organize your information with AI.</p>
        {!configured && (
          <div role="alert" className="mt-5 flex gap-2 rounded-md bg-amber-500/10 p-3 text-left text-sm text-amber-700 dark:text-amber-300">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            Firebase is not configured. Copy <code>frontend/.env.example</code> to <code>.env</code> and fill in your Firebase web app values.
          </div>
        )}
        {error && <p role="alert" className="mt-4 text-sm text-red-600">{error}</p>}
        <button className="btn-ghost mt-6 w-full py-3" disabled={!configured || busy} onClick={onClick}>
          <svg viewBox="0 0 48 48" className="h-5 w-5" aria-hidden="true">
            <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z" />
            <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 7.1-10.1 7.1-17.5z" />
            <path fill="#FBBC05" d="M10.5 28.7a14.5 14.5 0 010-9.4l-7.9-6.1a24 24 0 000 21.6l7.9-6.1z" />
            <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.9 2.3-8.4 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z" />
          </svg>
          Continue with Google
        </button>
      </div>
    </div>
  )
}
