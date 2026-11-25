-- Phase 8 hardening: the backend gets its OWN database role, and Supabase's public API roles get nothing.
--
-- Before: policies were "to authenticated" and keyed on Supabase's auth.uid(). Anyone able to obtain a Supabase
-- `authenticated` token (for example if email sign-ups were left enabled) could read/write their own rows directly
-- through Supabase's REST API, bypassing the backend's validation and limits.
-- After: only the backend (connecting as the table owner and doing SET ROLE datanest_api per request) can reach these
-- tables. The identity comes from the app.user_id setting that the backend derives from the verified Firebase token.
-- Safe to run more than once. Rollback: supabase/migrations/rollback/0004_rollback.sql

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'datanest_api') then
    create role datanest_api nologin;
  end if;
end $$;
grant datanest_api to postgres;

grant usage on schema public to datanest_api;
grant select, insert, update, delete on public.users, public.workspaces, public.sheets, public.records, public.files to datanest_api;
grant select, insert on public.activity_logs to datanest_api;  -- append-only for the app

create or replace function public.app_user_id() returns uuid
language sql stable as $$ select nullif(current_setting('app.user_id', true), '')::uuid $$;
grant execute on function public.app_user_id() to datanest_api;

-- replace the old "to authenticated / auth.uid()" policies
drop policy if exists users_self on public.users;
drop policy if exists workspaces_owner on public.workspaces;
drop policy if exists sheets_owner on public.sheets;
drop policy if exists records_owner on public.records;
drop policy if exists files_owner on public.files;
drop policy if exists activity_select on public.activity_logs;
drop policy if exists activity_insert on public.activity_logs;
drop policy if exists users_api on public.users;
drop policy if exists workspaces_api on public.workspaces;
drop policy if exists sheets_api on public.sheets;
drop policy if exists records_api on public.records;
drop policy if exists files_api on public.files;
drop policy if exists activity_select_api on public.activity_logs;
drop policy if exists activity_insert_api on public.activity_logs;

create policy users_api on public.users for all to datanest_api
  using (id = public.app_user_id()) with check (id = public.app_user_id());
create policy workspaces_api on public.workspaces for all to datanest_api
  using (user_id = public.app_user_id()) with check (user_id = public.app_user_id());
create policy sheets_api on public.sheets for all to datanest_api
  using (user_id = public.app_user_id()) with check (user_id = public.app_user_id());
create policy records_api on public.records for all to datanest_api
  using (user_id = public.app_user_id()) with check (user_id = public.app_user_id());
create policy files_api on public.files for all to datanest_api
  using (user_id = public.app_user_id()) with check (user_id = public.app_user_id());
create policy activity_select_api on public.activity_logs for select to datanest_api using (user_id = public.app_user_id());
create policy activity_insert_api on public.activity_logs for insert to datanest_api with check (user_id = public.app_user_id());

-- Supabase's public API roles can no longer touch these tables at all
revoke all on public.users, public.workspaces, public.sheets, public.records, public.files, public.activity_logs from anon, authenticated;
