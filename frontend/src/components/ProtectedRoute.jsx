import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Spinner } from './Spinner'

export function ProtectedRoute() {
  const { session, loading, configured } = useAuth()
  const location = useLocation()
  if (!configured) return <Navigate to="/login" replace />
  if (loading) return <Spinner full />
  if (!session) return <Navigate to="/login" replace state={{ from: location }} />
  return <Outlet />
}
