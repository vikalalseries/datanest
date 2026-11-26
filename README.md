# DataNest

DataNest turns unstructured information into organised, editable spreadsheets. Give it a **screenshot**, a **link**, or a **plain sentence**; Google Gemini extracts the fields, proposes the columns, and you decide whether to add the result to an existing sheet or create a new one. Everything is stored per user in Supabase and can be exported to Excel or CSV.

| | |
|---|---|
| Frontend | React 18, Vite, Tailwind, React Router (deployed on Vercel) |
| Backend | Python, FastAPI, SQLAlchemy (async), Pydantic (deployed on Render) |
| Database / storage | Supabase Postgres (JSONB records, Row Level Security) and Storage |
| Authentication | Firebase Authentication (Google sign-in), verified on the backend |
| AI | Google Gemini via the `google-genai` SDK |

Design notes and data model: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What it does

- **Smart Add**: screenshot, link or typed text → AI extraction → an editable preview (uncertain values are highlighted, nothing is invented) → add to an existing sheet (with column matching, duplicate detection and a mismatch explanation) or create a new sheet.
- **Spreadsheet editor**: nine column types, inline editing, sort, filter, search, multi-select, move rows between sheets, merge sheets, duplicate sheets, Trash, undo.
- **Excel / CSV**: export one sheet or everything (one worksheet per sheet); import `.xlsx` / `.csv` with a preview before anything is saved.
- **AI assistant**: ask questions about your data. Read-only: it can only *propose* changes, which you confirm.
- **Templates**: eight ready-made sheets, or describe one and AI designs it.
- **Insights**: job/internship funnel (applications, interviews, rejections, offers, response rate) and expense totals. Only shown for categories where they make sense.
- **Global search**, **activity history with undo**, **notifications** (deadlines, applications with no reply), light/dark theme.

## Run it locally

Prerequisites: Python 3.11+ (tested on 3.13), Node 20+ (tested on 24), a Supabase project, a Firebase project, a Gemini API key.

### 1. Supabase (database)
1. Create a project. In **SQL Editor** run, in order: `supabase/migrations/0001_init.sql`, `0002_firebase_auth.sql`, `0003_performance_indexes.sql`, `0004_dedicated_api_role.sql`. Each is safe to run twice.
2. **Authentication → Providers**: disable Email sign-ups. DataNest does not use Supabase Auth, and migration 0004 additionally removes all access for Supabase's public API roles.
3. Copy the project URL and the **Session pooler** connection string (Connect button) for `DATABASE_URL`.
4. For screenshot originals to be stored you need the project's **service role / secret key** in `SUPABASE_SERVICE_ROLE_KEY`; without it everything works except storing the original image.

### 2. Firebase (sign-in)
**Build → Authentication → Sign-in method → Google → Enable.** Add a **Web app** and copy its config into `frontend/.env`. Put the same project ID into `backend/.env` as `FIREBASE_PROJECT_ID`.

### 3. Configure and start
```powershell
copy backend\.env.example backend\.env       # fill in values (see the reference below)
copy frontend\.env.example frontend\.env

python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
cd backend ; ..\.venv\Scripts\python -m uvicorn app.main:app --reload     # http://localhost:8000

cd frontend ; npm install ; npm run dev                                    # http://localhost:5173
```

### Developing without logging in
Set `AUTH_DISABLED=true` in `backend/.env` and `VITE_AUTH_DISABLED=true` in `frontend/.env`, then restart both. Everything runs as one local user (`dev@localhost.test`). The backend **refuses to start** with this flag when `ENV=production`, and the frontend ignores it in production builds. Remove both lines before deploying or sharing the app. `python scripts/check_env.py backend/.env` tells you what would block a production start.

## Configuration reference

**`backend/.env`**

| Variable | Purpose |
|---|---|
| `ENV` | `development` (default) or `production` (enables startup safety checks, HSTS, hides `/docs`) |
| `DATABASE_URL` | Supabase Postgres connection string (use the pooler string on Render). Passwords with `@` or `/` are handled |
| `FIREBASE_PROJECT_ID` | Required to verify login tokens |
| `CORS_ORIGINS` | Comma-separated frontend URLs. In production: `https://` only, no wildcards, no localhost |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Storage of screenshot originals (server-side only) |
| `GEMINI_API_KEY` | Gemini key (server-side only) |
| `GEMINI_MODEL` | **API model id**, e.g. `gemini-3.5-flash-lite` (not the display name) |
| `GEMINI_FALLBACK_MODELS` | Tried in order when the main model is overloaded or out of quota |
| `MAX_UPLOAD_MB` | Screenshot size limit (default 5) |
| `AUTH_DISABLED` | Dev only, see above |

**`frontend/.env`**: `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID`, `VITE_FIREBASE_APP_ID`, `VITE_API_BASE_URL`, and (dev only) `VITE_AUTH_DISABLED`. Firebase web config values are public by design.

## About the AI (read this if extraction fails or is slow)

- **Free-tier limits are tight.** Google's free Gemini tier allows about **20 requests per day per model**, and models are frequently "overloaded" (HTTP 503) or slow (a trivial call can take 30 s). Each extraction costs one request; each assistant question costs two to four (one per tool step).
- DataNest copes by keeping a **chain of models**: when one is overloaded, out of quota or slow, the next one takes over immediately (a backup is started in parallel after 7 s), models that just failed are tried last, and each call has a hard time budget. The app shows a banner before you wait when no model is currently usable, a live timer while waiting, and a **Try again** button.
- When every model's daily quota is used up, the error says so and when it resets. You can keep working by hand; for sustained use, **enable billing on the Gemini API key**, which lifts the daily limit.
- Models available to your key: `python -c "from google import genai; print([m.name for m in genai.Client(api_key='KEY').models.list()])"`.
- Other protections: the assistant has no write tools (changes are proposals you confirm), cell text and web pages are treated as untrusted data, names in answers are checked against retrieved data, URL fetching is SSRF-protected, and uploads are validated and re-encoded.

## Testing

```powershell
cd backend ; ..\.venv\Scripts\python -m pytest                      # unit + security tests (no database needed)
$env:RLS_TEST=1 ; ..\.venv\Scripts\python -m pytest                 # + real-database suites (slow: ~20 min)
cd frontend ; npm test                                              # component and page tests
```

The `RLS_TEST=1` suites create throwaway users (their emails end in `.invalid`) in the database from `backend/.env`, test through the real API, and delete them afterwards. **Run them against a test project, not a database holding data you care about.** They cover: cross-user isolation on every endpoint, the database role model (Supabase's public roles have no access; the audit log is append-only), validation and atomic saves, export/import round trips, AI endpoints with a scripted fake Gemini, and the assistant's safety properties. Gemini is never called by the test suites.

## Security summary

- **Identity**: Firebase ID tokens verified on every request (signature, expiry, audience, issuer); the user id never comes from the request body.
- **Isolation, twice**: every query filters by user, *and* Postgres Row Level Security enforces it for the dedicated `datanest_api` role. Supabase's `anon`/`authenticated` roles have no table access at all.
- **Inputs**: Pydantic validation everywhere; parameterised SQL (sort/filter columns are validated against the sheet schema); file type decided by content, size-capped, images re-encoded (metadata stripped); spreadsheet formulas are never evaluated and formula-looking text is neutralised on export.
- **SSRF**: link extraction refuses private/loopback/link-local/internal addresses (including via redirects and DNS tricks), non-web ports and credentials in URLs, pins the validated IP, and caps size and time.
- **Operations**: rate limits (120/min default, 10-20/min on AI, import and export), safe error responses (code, message, request id, never a stack trace or secret), secrets only in environment variables, startup refuses unsafe production settings.
- **Dependencies**: `npm audit` and `pip-audit` report no known vulnerabilities at the time of writing; backend versions are pinned in `requirements.lock`.

## Deploying

Order: Supabase → Firebase → Render (API) → Vercel (frontend) → connect them → verify.

1. **Supabase**: run the four migrations (above).
2. **Check your config**: `python scripts/check_env.py backend/.env` (lists what is unsafe for production).
3. **Render** (API): New → **Web Service** → connect this repo, then use these settings:

   | Setting | Value |
   |---|---|
   | Language | Python 3 |
   | Branch | `main` |
   | Region | The one closest to your Supabase database |
   | Root Directory | `backend` |
   | Build Command | `pip install -r requirements.lock` |
   | Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'` |
   | Health Check Path | `/health` |

   `--proxy-headers` lets rate limiting see each visitor's real IP instead of Render's proxy.

   Add these environment variables (see [Configuration reference](#configuration-reference)):

   | Variable | Value |
   |---|---|
   | `PYTHON_VERSION` | `3.13.5` (CI tests with Python 3.13) |
   | `ENV` | `production` |
   | `FIREBASE_PROJECT_ID` | Your Firebase project id |
   | `DATABASE_URL` | Supabase **Session pooler** connection string |
   | `CORS_ORIGINS` | Your Vercel URL, `https://` and no trailing slash (a placeholder is fine until step 5) |
   | `SUPABASE_URL` | Your Supabase project URL |
   | `SUPABASE_SERVICE_ROLE_KEY` | Your Supabase service role key |
   | `GEMINI_API_KEY` | Your Gemini key |
   | `GEMINI_MODEL` | `gemini-3.5-flash-lite` |
   | `GEMINI_FALLBACK_MODELS` | `gemini-3.1-flash-lite,gemini-3.5-flash,gemini-3.6-flash,gemini-3.7-flash` |
   | `MAX_UPLOAD_MB` | `5` |

   Do not set `AUTH_DISABLED`. On the free plan the service sleeps after ~15 min idle; the first request afterwards takes 30-60 s.
4. **Vercel** (frontend): import the repo, set **Root Directory** to `frontend`, and add the `VITE_FIREBASE_*` variables plus `VITE_API_BASE_URL` = your Render URL. Do not set `VITE_AUTH_DISABLED`.
5. **Connect**: set Render's `CORS_ORIGINS` to the final Vercel URL (add your custom domain if any). In Firebase → Authentication → Settings → **Authorized domains**, add the Vercel domain.
6. **Verify**: `python scripts/smoke_test.py https://YOUR-API.onrender.com --origin https://YOUR-APP.vercel.app` should pass every check (login required, docs hidden, headers, CORS, HTTPS/HSTS). Then sign in with Google in the browser and run through Smart Add once.
7. **Tighten the browser policy**: `frontend/vercel.json` ships a `Content-Security-Policy-Report-Only` header so a policy mistake can't break sign-in. Open the deployed app with the browser console open and use sign-in, search and the assistant. If there are no violation reports, rename the header to `Content-Security-Policy` to enforce it (replace `*.onrender.com` with your exact API host).

Continuous integration (`.github/workflows/ci.yml`) runs the backend unit tests and the frontend tests and build on every push.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| "The AI service is very busy right now" | Gemini overload; the app already tried every model. Try again in a moment |
| "Today's free AI quota is used up" | Daily free limit reached on all models; resets at the time shown, or enable billing |
| "AI features aren't configured" | `GEMINI_API_KEY` / `GEMINI_MODEL` missing |
| Google sign-in popup error | Domain missing from Firebase *Authorized domains*, or Google provider not enabled |
| Browser shows CORS errors | `CORS_ORIGINS` doesn't exactly match the frontend URL (scheme and host, no trailing slash) |
| Everything 401 after deploy | `FIREBASE_PROJECT_ID` on the backend doesn't match the frontend's project |
| Backend won't start in production | It lists the unsafe setting in its log (for example `AUTH_DISABLED` or a localhost CORS origin) |
| "The original image couldn't be stored" | `SUPABASE_SERVICE_ROLE_KEY` is missing or isn't the service/secret key |

## Project layout

```
backend/app/    api/ (routers)  services/ (business logic, AI, import/export)  database/  middleware/  utils/
backend/tests/  unit, security and real-database suites
frontend/src/   pages/  components/  services/ (API clients)  context/  hooks/  layouts/
supabase/migrations/   0001-0004 (+ rollback/)
scripts/        check_env.py  smoke_test.py  make_lock.py
frontend/vercel.json     .github/workflows/ci.yml
```
