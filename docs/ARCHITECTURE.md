# DataNest: architecture (as built)

## System

```
Browser (React, Vite, Tailwind: Vercel)
   │  Google sign-in via Firebase Auth (browser only holds Firebase's public web config)
   │  every API call carries  Authorization: Bearer <Firebase ID token>
   ▼
FastAPI (Render)
   ├─ middleware   request id · security headers · CORS · rate limits · gzip · safe error responses
   ├─ auth         verify Firebase token (RS256, audience, issuer, expiry) → Firebase uid
   ├─ api/         thin routers: validation + dependency wiring only
   ├─ services/    business logic: sheets, records, matching, extraction, assistant, import/export, analytics ...
   └─ database/    async SQLAlchemy → one transaction per request, scoped to one user
         │                       │                        │
         ▼                       ▼                        ▼
   Supabase Postgres       Supabase Storage        Google Gemini API
   (JSONB, RLS)            (private bucket)        (model chain with fallback)
```

The browser never talks to the database. Supabase is used only as Postgres and file storage; sign-in is Firebase.

## Request lifecycle and the identity model

1. The Firebase token is verified; `uid` (Firebase's id) is read from the **verified** token only.
2. `resolve_user_id` maps it to an internal UUID (`users.firebase_uid` → `users.id`), creating the profile and default workspace on first login (cached in memory; the mapping never changes).
3. A transaction opens and executes `set_config('app.user_id', <uuid>, true)` and `set_config('role', 'datanest_api', true)`.
4. Every statement now runs as the least-privileged `datanest_api` role. Row Level Security policies on every table allow only rows where `user_id = app_user_id()`. Services additionally filter by `user_id` explicitly (defence in depth).
5. The transaction commits on success and rolls back on any error, so multi-step operations (create sheet + rows, import, merge, bulk add) are atomic.

Supabase's `anon` and `authenticated` roles have **no privileges** on these tables (migration 0004), so Supabase's own REST API cannot reach user data even if someone obtains a Supabase token.

## Data model

| Table | Notes |
|---|---|
| `users` | `id` (internal UUID), `firebase_uid` (unique), email, name, avatar, preferences |
| `workspaces` | one default workspace per user |
| `sheets` | name, description, `category` (drives insights), `schema_json` = ordered columns `{id, name, type, options?}`, `template_key`, `deleted_at` (Trash) |
| `records` | `data_json` JSONB keyed by **stable column id** (renaming a column rewrites nothing), `source_type` (manual/image/url/text/import/ai_assistant), `source_url`, `source_file_id`, `position` (stable order inside a batch), `deleted_at` |
| `files` | uploaded originals (private Storage bucket `uploads/{user}/{uuid}`), downloaded through short-lived signed links |
| `activity_logs` | append-only audit trail with before/after details; powers the activity feed and undo |

Column types: text, number, currency, date, boolean, email, url, status, tags. Values are validated and normalised per type on every write (`utils/validators.py`). Migration history: `0001` schema + RLS, `0002` Firebase identity, `0003` performance indexes, `0004` dedicated API role.

## AI pipeline

```
screenshot ─ validate by content, size cap, re-encode (strips metadata) ─┐
link ────── SSRF-safe fetch → text + JSON-LD (no scripts executed) ──────┼→ Gemini (structured JSON schema)
typed text ───────────────────────────────────────────────────────────────┘        │
                                                                                   ▼
        Pydantic validation → normalisation (types coerced; unreadable values kept raw and flagged; unknown → null)
                                                                                   ▼
                          editable preview → choose destination → atomic save (nothing dropped silently)
```

- **Model chain** (`services/gemini_service.py`): `GEMINI_MODEL`, then `GEMINI_FALLBACK_MODELS`. An overloaded, out-of-quota or failing model hands over immediately; a merely *slow* model gets a parallel backup after 7 s and the first answer wins; models that just failed are tried last (backing off up to 5 min); each call has a hard time budget; quota errors report the real reset time. `GET /api/ai/status` exposes this state without using quota.
- **Matching** (`services/matching_service.py`): exact / synonym / fuzzy name match with type compatibility first; Gemini only resolves leftovers and its answers are validated. Mapping must account for every field that has data (map, create a column, or an explicit skip). Duplicate detection compares normalised values and requires a meaningful identifying match.
- **Assistant** (`services/assistant_service.py`): Gemini function calling over a fixed allowlist of read tools (list sheets, query, aggregate, search, find duplicates) plus two *propose* tools that never write. Proposals are written only by `POST /api/ai/chat/confirm`, which re-validates ownership, columns and types. Answers are grounded: names not present in retrieved data trigger one correction and then a visible warning. Tool loops are capped and conversations stay pinned to one model.

## Security layers

Verified identity → per-request user scope → RLS under a restricted role → validated inputs → parameterised SQL → SSRF guard on outbound fetches → content-based upload validation → read-only assistant with confirmation → rate limits → generic error bodies and request ids → secrets only in environment variables → production startup refuses unsafe settings (`AUTH_DISABLED`, wildcard or local CORS, missing identity config).

## API surface (53 endpoints)

`/api/auth/me` · sheets (`/api/sheets`, columns, duplicate, merge, restore, permanent delete, `from-extraction`) · records (CRUD, bulk delete/restore/purge/move, `bulk` add with mapping, `check-duplicates`) · `/api/ai/*` (extract text/image/url, rank-sheets, match-columns, suggest-sheet, generate-template, chat, chat/confirm, status) · `/api/import/{preview,commit}` · `/api/export/{sheet,workspace}` · `/api/files/{id}/download` · `/api/search` (+ facets) · `/api/analytics/{sheet,overview}` · `/api/activity` (+ undo) · `/api/notifications` · `/api/templates` · `/api/dashboard/stats` · `/api/trash` · `/health`. The interactive schema is at `/docs` outside production.

## Frontend structure

Pages are lazy-loaded; vendor libraries (React, Firebase) are separate cacheable chunks. API clients live in `src/services`; the auth context attaches the Firebase token and signs out on a rejected token. Shared UI (modals, toasts, cells, filters, the extraction preview, the assistant's proposal cards) is in `src/components`. Rows in the grid are memoised so editing one cell doesn't re-render the page.

## Deliberate trade-offs and known limits

- **Records are JSONB, not columns.** Maximum flexibility and no migrations per sheet; cross-sheet SQL aggregates are done in Python for analytics (capped at 20,000 rows/sheet) rather than SQL.
- **Grid pagination, not virtualisation** (100 rows per page); fine into the thousands, not for single sheets with tens of thousands of visible rows.
- **Undo** is limited to edits, added rows, deleted rows and deleted sheets, and refuses when it would overwrite newer edits. Imports and merges are recoverable through Trash and export, not undo.
- **Rate limiting and model-health memory are per process.** One Render instance is assumed; with several instances use a shared store (e.g. Redis) for limits.
- **Insights and notifications infer meaning from column names and status words**, so unusual vocabulary can be missed (the UI says what wasn't counted).
- **Free Gemini tier**: ~20 requests/day/model and frequent overload; mitigated by the model chain and clear messaging, solved by enabling billing.
