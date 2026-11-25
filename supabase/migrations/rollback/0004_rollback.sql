-- Undo 0004: go back to Supabase's "authenticated" role + auth.uid() policies.
-- (Also change backend/app/database/connection.py back to set_config('role','authenticated') and request.jwt.claims.)
grant select, insert, update, delete on public.users, public.workspaces, public.sheets, public.records, public.files to authenticated;
grant select, insert on public.activity_logs to authenticated;
drop policy if exists users_api on public.users;
drop policy if exists workspaces_api on public.workspaces;
drop policy if exists sheets_api on public.sheets;
drop policy if exists records_api on public.records;
drop policy if exists files_api on public.files;
drop policy if exists activity_select_api on public.activity_logs;
drop policy if exists activity_insert_api on public.activity_logs;
create policy users_self on public.users for all to authenticated using (id = (select auth.uid())) with check (id = (select auth.uid()));
create policy workspaces_owner on public.workspaces for all to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy sheets_owner on public.sheets for all to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy records_owner on public.records for all to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy files_owner on public.files for all to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy activity_select on public.activity_logs for select to authenticated using (user_id = (select auth.uid()));
create policy activity_insert on public.activity_logs for insert to authenticated with check (user_id = (select auth.uid()));
