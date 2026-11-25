-- DataNest initial schema. Run in Supabase SQL editor (or `supabase db push`).
create extension if not exists pgcrypto;
create extension if not exists pg_trgm;

-- ---------- tables ----------
create table if not exists public.users (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  full_name text,
  avatar_url text,
  preferences jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists public.workspaces (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  name text not null default 'My Workspace',
  created_at timestamptz not null default now()
);
create index if not exists workspaces_user_idx on public.workspaces(user_id);

create table if not exists public.sheets (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  user_id uuid not null references public.users(id) on delete cascade,
  name text not null,
  description text,
  category text not null default 'general',
  schema_json jsonb not null default '{"columns":[]}',
  template_key text,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists sheets_user_idx on public.sheets(user_id, deleted_at, updated_at desc);
create index if not exists sheets_workspace_idx on public.sheets(workspace_id);
create index if not exists sheets_name_trgm on public.sheets using gin (name gin_trgm_ops);

create table if not exists public.files (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  file_name text not null,
  file_path text not null,
  file_type text not null,
  size_bytes bigint,
  created_at timestamptz not null default now()
);
create index if not exists files_user_idx on public.files(user_id);

create table if not exists public.records (
  id uuid primary key default gen_random_uuid(),
  sheet_id uuid not null references public.sheets(id) on delete cascade,
  user_id uuid not null references public.users(id) on delete cascade,
  data_json jsonb not null default '{}',
  source_type text not null default 'manual'
    check (source_type in ('manual','image','url','text','import','ai_assistant')),
  source_url text,
  source_file_id uuid references public.files(id) on delete set null,
  position double precision,
  ai_meta jsonb,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists records_sheet_idx on public.records(sheet_id, deleted_at, created_at desc);
create index if not exists records_user_idx on public.records(user_id);
create index if not exists records_data_gin on public.records using gin (data_json jsonb_path_ops);
create index if not exists records_text_trgm on public.records using gin ((lower(data_json::text)) gin_trgm_ops);

create table if not exists public.activity_logs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  sheet_id uuid references public.sheets(id) on delete set null,
  action text not null,
  details_json jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index if not exists activity_user_idx on public.activity_logs(user_id, created_at desc);
create index if not exists activity_sheet_idx on public.activity_logs(sheet_id);

-- ---------- triggers ----------
create or replace function public.touch_updated_at() returns trigger
language plpgsql as $$
begin new.updated_at = now(); return new; end $$;

drop trigger if exists sheets_touch on public.sheets;
create trigger sheets_touch before update on public.sheets
  for each row execute function public.touch_updated_at();
drop trigger if exists records_touch on public.records;
create trigger records_touch before update on public.records
  for each row execute function public.touch_updated_at();

-- ownership consistency: child rows must belong to the same user as the parent
create or replace function public.check_sheet_owner() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if not exists (select 1 from public.workspaces w
                 where w.id = new.workspace_id and w.user_id = new.user_id) then
    raise exception 'workspace does not belong to user';
  end if;
  return new;
end $$;
drop trigger if exists sheets_owner_check on public.sheets;
create trigger sheets_owner_check before insert or update of workspace_id, user_id on public.sheets
  for each row execute function public.check_sheet_owner();

create or replace function public.check_record_owner() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if not exists (select 1 from public.sheets s
                 where s.id = new.sheet_id and s.user_id = new.user_id) then
    raise exception 'sheet does not belong to user';
  end if;
  return new;
end $$;
drop trigger if exists records_owner_check on public.records;
create trigger records_owner_check before insert or update of sheet_id, user_id on public.records
  for each row execute function public.check_record_owner();

-- profile + default workspace on signup (Google metadata)
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.users (id, email, full_name, avatar_url)
  values (new.id, coalesce(new.email, ''),
          coalesce(new.raw_user_meta_data->>'full_name', new.raw_user_meta_data->>'name'),
          coalesce(new.raw_user_meta_data->>'avatar_url', new.raw_user_meta_data->>'picture'))
  on conflict (id) do nothing;
  insert into public.workspaces (user_id, name) values (new.id, 'My Workspace');
  return new;
end $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------- Row Level Security ----------
alter table public.users enable row level security;
alter table public.workspaces enable row level security;
alter table public.sheets enable row level security;
alter table public.records enable row level security;
alter table public.files enable row level security;
alter table public.activity_logs enable row level security;

drop policy if exists users_self on public.users;
create policy users_self on public.users for all to authenticated
  using (id = (select auth.uid())) with check (id = (select auth.uid()));

drop policy if exists workspaces_owner on public.workspaces;
create policy workspaces_owner on public.workspaces for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists sheets_owner on public.sheets;
create policy sheets_owner on public.sheets for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists records_owner on public.records;
create policy records_owner on public.records for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists files_owner on public.files;
create policy files_owner on public.files for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

-- activity log is append-only for users
drop policy if exists activity_select on public.activity_logs;
create policy activity_select on public.activity_logs for select to authenticated
  using (user_id = (select auth.uid()));
drop policy if exists activity_insert on public.activity_logs;
create policy activity_insert on public.activity_logs for insert to authenticated
  with check (user_id = (select auth.uid()));

-- no access for anon
revoke all on public.users, public.workspaces, public.sheets, public.records,
  public.files, public.activity_logs from anon;
