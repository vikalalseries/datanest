-- Phase 7 performance: indexes for the new global search / activity / dashboard queries. Safe to run more than once.
create index if not exists sheets_user_category_idx on public.sheets (user_id, category) where deleted_at is null;
create index if not exists records_user_updated_idx on public.records (user_id, updated_at desc) where deleted_at is null;
create index if not exists records_sheet_position_idx on public.records (sheet_id, created_at, position) where deleted_at is null;
create index if not exists activity_sheet_created_idx on public.activity_logs (user_id, sheet_id, created_at desc);
create index if not exists activity_undo_of_idx on public.activity_logs ((details_json ->> 'of')) where action = 'activity.undo';
