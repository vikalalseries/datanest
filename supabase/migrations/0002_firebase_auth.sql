-- Switch identity from Supabase Auth to Firebase Auth.
-- public.users.id stays an internal UUID (all existing FKs/RLS keep working);
-- the backend maps the verified Firebase uid -> this UUID and sets it as the RLS identity.

drop trigger if exists on_auth_user_created on auth.users;
drop function if exists public.handle_new_user();

alter table public.users drop constraint if exists users_id_fkey;
alter table public.users alter column id set default gen_random_uuid();
alter table public.users add column if not exists firebase_uid text;
create unique index if not exists users_firebase_uid_key on public.users(firebase_uid);

-- Safety: Supabase's own anon/authenticated API roles must not be able to self-register data.
-- The backend uses the table owner connection and `set role authenticated` per request, so
-- also disable Supabase email/password sign-ups in the dashboard (Authentication -> Providers).
revoke all on public.users, public.workspaces, public.sheets, public.records,
  public.files, public.activity_logs from anon;
