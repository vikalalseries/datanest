import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const INPUTS = [
  { title: 'Screenshot', text: 'Drop an image and DataNest reads it.' },
  { title: 'Link', text: 'Paste a job or internship URL.' },
  { title: 'Plain text', text: 'Just describe it in your own words.' },
]

export default function Landing() {
  const { session } = useAuth()
  const to = session ? '/dashboard' : '/login'
  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-4 py-5">
        <span className="text-2xl font-bold tracking-tight">DataNest</span>
        <Link to={to} className="btn-ghost">{session ? 'Open dashboard' : 'Sign in'}</Link>
      </header>
      <section className="mx-auto max-w-5xl px-4 py-14 sm:py-20">
        <h1 className="max-w-2xl text-3xl font-semibold tracking-tight sm:text-5xl">Give it information. Get an organized spreadsheet.</h1>
        <p className="mt-5 max-w-xl text-base text-soft sm:text-lg">
          DataNest uses AI to turn screenshots, links and plain sentences into structured records you can edit, search and export. No columns to design.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link to={to} className="btn-primary px-6 py-3 text-base">Get started</Link>
          <Link to="/about" className="btn-ghost px-6 py-3 text-base">About DataNest</Link>
        </div>
      </section>
      <section className="mx-auto max-w-5xl px-4 pb-20">
        <h2 className="text-sm font-semibold text-soft">Three ways to add information</h2>
        <div className="mt-3 grid gap-4 sm:grid-cols-3">
          {INPUTS.map(({ title, text }) => (
            <div key={title} className="card p-5">
              <h3 className="font-semibold">{title}</h3>
              <p className="mt-1 text-sm text-soft">{text}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
