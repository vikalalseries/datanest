import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { ProtectedRoute } from './components/ProtectedRoute'
import { Spinner } from './components/Spinner'
import { AppLayout } from './layouts/AppLayout'
import { AboutLayout } from './layouts/AboutLayout'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'

// Heavier screens load on demand so the first page opens fast.
const Profile = lazy(() => import('./pages/Profile'))
const Settings = lazy(() => import('./pages/Settings'))
const MySheets = lazy(() => import('./pages/MySheets'))
const SheetEditor = lazy(() => import('./pages/SheetEditor'))
const AllRecords = lazy(() => import('./pages/AllRecords'))
const Trash = lazy(() => import('./pages/Trash'))
const SmartAdd = lazy(() => import('./pages/SmartAdd'))
const ImportPage = lazy(() => import('./pages/ImportPage'))
const AssistantPage = lazy(() => import('./pages/AssistantPage'))
const Templates = lazy(() => import('./pages/Templates'))
const SearchPage = lazy(() => import('./pages/SearchPage'))
const ActivityPage = lazy(() => import('./pages/ActivityPage'))
const About = lazy(() => import('./pages/About'))

export default function App() {
  return (
    <Suspense fallback={<div className="p-8"><Spinner /></div>}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route element={<AboutLayout />}>
          <Route path="/about" element={<About />} />
        </Route>
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/add" element={<SmartAdd />} />
            <Route path="/import" element={<ImportPage />} />
            <Route path="/sheets" element={<MySheets />} />
            <Route path="/sheets/:sheetId" element={<SheetEditor />} />
            <Route path="/records" element={<AllRecords />} />
            <Route path="/assistant" element={<AssistantPage />} />
            <Route path="/templates" element={<Templates />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/activity" element={<ActivityPage />} />
            <Route path="/trash" element={<Trash />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/profile" element={<Profile />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}
