"""RLS isolation test. Runs against a REAL Supabase DB; skipped unless RLS_TEST=1 and DATABASE_URL are set.

It creates two throwaway users, inserts a sheet for A, and proves B can neither see nor modify it
through the same RLS context the API uses. Everything is cleaned up afterwards.
"""
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database.connection import apply_rls_context

pytestmark = pytest.mark.skipif(
    os.environ.get("RLS_TEST") != "1" or not get_settings().database_url,
    reason="set RLS_TEST=1 and DATABASE_URL to run against a real database",
)


@pytest.mark.asyncio
async def test_user_b_cannot_access_user_a_data():
    engine = create_async_engine(get_settings().async_database_url, connect_args={"statement_cache_size": 0})
    sm = async_sessionmaker(engine, expire_on_commit=False)
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        async with sm() as s, s.begin():  # setup as table owner (no RLS context)
            for uid in (a, b):
                await s.execute(
                    text("insert into public.users (id, email, firebase_uid) values (:i, :e, :f)"),
                    {"i": uid, "e": f"{uid}@rls-test.invalid", "f": f"rls-test-{uid}"},
                )
                await s.execute(text("insert into public.workspaces (user_id) values (:i)"), {"i": uid})
            ws = (await s.execute(text("select id from public.workspaces where user_id = :u"), {"u": a})).scalar_one()
            sheet = (
                await s.execute(
                    text("insert into public.sheets (workspace_id, user_id, name) values (:w, :u, 'secret') returning id"),
                    {"w": ws, "u": a},
                )
            ).scalar_one()

        async with sm() as s, s.begin():
            await apply_rls_context(s, a)
            assert (await s.execute(text("select count(*) from public.sheets"))).scalar_one() == 1

        async with sm() as s, s.begin():
            await apply_rls_context(s, b)
            assert (await s.execute(text("select count(*) from public.sheets"))).scalar_one() == 0
            upd = await s.execute(text("update public.sheets set name='pwned' where id=:i"), {"i": sheet})
            assert upd.rowcount == 0
            dele = await s.execute(text("delete from public.sheets where id=:i"), {"i": sheet})
            assert dele.rowcount == 0
            with pytest.raises(Exception):  # cannot insert a sheet for A's workspace/user
                await s.execute(
                    text("insert into public.sheets (workspace_id, user_id, name) values (:w, :u, 'x')"), {"w": ws, "u": a}
                )
    finally:
        async with sm() as s, s.begin():
            await s.execute(text("delete from public.users where email like '%@rls-test.invalid'"))
        await engine.dispose()


TABLES = ["users", "workspaces", "sheets", "records", "files", "activity_logs"]


async def _session():
    engine = create_async_engine(get_settings().async_database_url, connect_args={"statement_cache_size": 0})
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_every_table_has_rls_and_supabase_public_roles_have_no_access():
    """Guards against a future migration quietly re-opening the tables to Supabase's REST API."""
    engine, sm = await _session()
    try:
        async with sm() as s, s.begin():
            for t in TABLES:
                assert (await s.execute(text("select relrowsecurity from pg_class where oid = ('public.' || :t)::regclass"), {"t": t})).scalar_one() is True, t
                for role in ("anon", "authenticated"):
                    for priv in ("select", "insert", "update", "delete"):
                        has = (await s.execute(text("select has_table_privilege(:r, 'public.' || :t, :p)"), {"r": role, "t": t, "p": priv})).scalar_one()
                        assert has is False, f"{role} must not have {priv} on {t}"
            n = (await s.execute(text("select count(distinct tablename) from pg_policies where schemaname = 'public' and roles = '{datanest_api}'"))).scalar_one()
            assert n == len(TABLES)  # every table has a policy for the API role
            assert (await s.execute(text("select count(*) from pg_policies where schemaname = 'public' and ('authenticated' = any(roles) or 'anon' = any(roles) or 'public' = any(roles))"))).scalar_one() == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_supabase_authenticated_role_cannot_read_or_write_even_with_a_forged_identity():
    engine, sm = await _session()
    try:
        for role in ("authenticated", "anon"):
            async with sm() as s:
                async with s.begin():
                    await s.execute(text(f"set local role {role}"))
                    await s.execute(text("select set_config('request.jwt.claims', '{\"sub\":\"11111111-1111-1111-1111-111111111111\"}', true)"))
                    with pytest.raises(Exception) as e:
                        await s.execute(text("select count(*) from public.sheets"))
                    assert "permission denied" in str(e.value).lower()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_api_role_without_an_identity_sees_nothing_and_activity_log_is_append_only():
    engine, sm = await _session()
    uid = str(uuid.uuid4())
    try:
        async with sm() as s, s.begin():
            await s.execute(text("insert into public.users (id, email, firebase_uid) values (:i, :e, :f)"), {"i": uid, "e": f"{uid}@rls-test.invalid", "f": f"rls-test-{uid}"})
            await s.execute(text("insert into public.workspaces (user_id) values (:i)"), {"i": uid})
        async with sm() as s, s.begin():  # role set but no user identity at all
            await s.execute(text("select set_config('role', 'datanest_api', true)"))
            for t in ("users", "workspaces", "sheets", "records", "files", "activity_logs"):
                assert (await s.execute(text(f"select count(*) from public.{t}"))).scalar_one() == 0, t
        async with sm() as s, s.begin():
            await apply_rls_context(s, uid)
            await s.execute(text("insert into public.activity_logs (user_id, action) values (:u, 'test')"), {"u": uid})
            assert (await s.execute(text("select count(*) from public.activity_logs"))).scalar_one() == 1
            for stmt in ("update public.activity_logs set action = 'x'", "delete from public.activity_logs"):
                with pytest.raises(Exception) as e:
                    async with s.begin_nested():
                        await s.execute(text(stmt))
                assert "permission denied" in str(e.value).lower(), stmt  # users cannot rewrite their own audit trail
    finally:
        async with sm() as s, s.begin():
            await s.execute(text("delete from public.users where email like '%@rls-test.invalid'"))
        await engine.dispose()
