import { Link, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Spinner } from '../components/Spinner'
import { AppLayout } from './AppLayout'

/** The About page is public: signed-in users see it inside the app, visitors see it with a simple header. */
export function AboutLayout() {
  const { session, loading } = useAuth()
  if (loading) return <Spinner full />
  if (session) return <AppLayout />
  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-3xl items-center justify-between px-4 py-5">
        <Link to="/" className="text-2xl font-bold tracking-tight">DataNest</Link>
        <Link to="/login" className="btn-ghost">Sign in</Link>
      </header>
      <main className="mx-auto max-w-3xl px-4 pb-20"><Outlet /></main>
    </div>
  )
}
