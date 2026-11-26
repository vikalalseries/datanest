import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const STEPS = [
  ['Add information', 'Upload a screenshot, paste a link to a public page, or describe it in your own words.'],
  ['Review the result', 'AI picks out the details and shows them in a table. Fix anything that looks wrong; uncertain values are highlighted.'],
  ['Save it', 'Add the rows to an existing sheet or create a new one. Nothing is saved until you confirm.'],
]

const USES = [
  ['Job and internship applications', 'Track companies, roles, dates and status, and see your interviews, offers and response rate.'],
  ['Expenses', 'Note what you spent in a sentence and see your totals.'],
  ['Tasks and deadlines', 'Keep assignments and due dates together, with reminders in the notification bell.'],
  ['Anything else you list', 'Contacts, study plans, reading lists: start from a template or describe the sheet you want.'],
]

const FEATURES = [
  ['Sheets', '/sheets', 'Edit cells directly, sort, filter, move rows, merge or duplicate sheets.'],
  ['All records', '/records', 'See the rows from all your sheets in one place.'],
  ['Assistant', '/assistant', 'Ask questions about your data. It only suggests changes; you decide whether to apply them.'],
  ['Templates', '/templates', 'Start with a ready-made sheet, or let AI design one from your description.'],
  ['Import', '/import', 'Bring in an Excel (.xlsx) or CSV file and preview it before saving.'],
  ['Activity', '/activity', 'See what changed and undo changes.'],
  ['Trash', '/trash', 'Restore deleted sheets and rows, or remove them permanently.'],
  ['Settings', '/settings', 'Switch to the dark theme, or export everything to one Excel workbook.'],
]

function Section({ title, children }) {
  return (
    <section aria-label={title} className="mt-8">
      <h2 className="font-semibold">{title}</h2>
      {children}
    </section>
  )
}

export default function About() {
  const { session } = useAuth()
  return (
    <div className="w-full">
      {/* Inside the app, phones already show the title in the top bar */}
      <h1 className={`text-2xl font-semibold ${session ? 'max-lg:sr-only' : ''}`}>About DataNest</h1>
      <p className="mt-3 text-soft">
        DataNest turns scattered information into organised spreadsheets you can edit, search and export. You don't need to design columns or type
        everything by hand: give it a screenshot, a link or a sentence, and AI does the first draft for you.
      </p>

      <Section title="How it works">
        <ol className="mt-2 grid gap-3 text-sm md:grid-cols-3">
          {STEPS.map(([title, text], i) => (
            <li key={title} className="card flex gap-3 p-4">
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold" aria-hidden="true">{i + 1}</span>
              <div><p className="font-medium">{title}</p><p className="mt-0.5 text-soft">{text}</p></div>
            </li>
          ))}
        </ol>
        <Link to={session ? '/add' : '/login'} className="btn-primary mt-3">{session ? 'Add information' : 'Get started'}</Link>
      </Section>

      <Section title="How it helps you">
        <div className="mt-2 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {USES.map(([title, text]) => (
            <div key={title} className="card p-4 text-sm"><h3 className="font-medium">{title}</h3><p className="mt-1 text-soft">{text}</p></div>
          ))}
        </div>
      </Section>

      <Section title="What you can do">
        <ul className="mt-2 grid gap-3 text-sm md:grid-cols-2">
          {FEATURES.map(([label, to, text]) => (
            <li key={to} className="card flex flex-col gap-0.5 p-4 sm:flex-row sm:gap-4">
              {session
                ? <Link to={to} className="shrink-0 font-medium text-brand hover:underline sm:w-28">{label}</Link>
                : <span className="shrink-0 font-medium sm:w-28">{label}</span>}
              <span className="text-soft">{text}</span>
            </li>
          ))}
        </ul>
      </Section>

      <div className="grid gap-x-8 md:grid-cols-2">
        <Section title="Your data and privacy">
          <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm text-soft">
            <li>You sign in with Google, and your sheets are visible only to your account.</li>
            <li>To read your input and answer questions, DataNest sends the relevant content to Google's Gemini AI. Don't add passwords or other highly sensitive information.</li>
            <li>Uploaded screenshots may be stored with your account.</li>
            <li>You can export your data to Excel at any time.</li>
          </ul>
        </Section>

        <Section title="Good to know">
          <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm text-soft">
            <li>AI can make mistakes, so check the preview before saving.</li>
            <li>The AI has usage limits and can be busy or slow. You can always keep working by hand.</li>
            <li>Screenshots can be JPG, PNG or WEBP, up to 5 MB. Only public web pages can be read from a link.</li>
          </ul>
        </Section>
      </div>
    </div>
  )
}
