"""Async DB engine + per-request RLS context.

The verified Firebase uid is mapped to an internal user UUID. Every request then runs in one
transaction where we set that UUID as `app.user_id` and switch to the `datanest_api` role, so Postgres RLS
enforces ownership in addition to the service-layer checks.
"""
from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.middleware.authentication import AuthUser, get_current_user

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_uid_cache: dict[str, str] = {}  # firebase uid -> internal uuid (mapping never changes)


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.async_database_url,
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
            # required when going through Supabase's pgbouncer (transaction mode)
            connect_args={"statement_cache_size": 0},
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def resolve_user_id(user: AuthUser) -> str:
    """Find or create the internal user (+ default workspace) for a verified Firebase identity."""
    cached = _uid_cache.get(user.uid)
    if cached:
        return cached
    get_engine()
    assert _sessionmaker is not None
    async with _sessionmaker() as s, s.begin():  # owner connection, before RLS context
        row = (
            await s.execute(
                text(
                    "insert into public.users (firebase_uid, email, full_name, avatar_url) "
                    "values (:uid, :email, :name, :pic) "
                    "on conflict (firebase_uid) do update set "
                    "  email = excluded.email, "
                    "  full_name = coalesce(excluded.full_name, public.users.full_name), "
                    "  avatar_url = coalesce(excluded.avatar_url, public.users.avatar_url) "
                    "returning id"
                ),
                {"uid": user.uid, "email": user.email, "name": user.name, "pic": user.picture},
            )
        ).one()
        internal = str(row.id)
        await s.execute(
            text(
                "insert into public.workspaces (user_id) select :u "
                "where not exists (select 1 from public.workspaces where user_id = :u)"
            ),
            {"u": internal},
        )
    _uid_cache[user.uid] = internal
    return internal


async def apply_rls_context(session: AsyncSession, user_id: str, email: str = "") -> None:
    """Scope this transaction to one user: set the identity the RLS policies read and drop to the least-privileged role.

    `datanest_api` (migration 0004) can only see rows where user_id = app.user_id, and Supabase's own public roles
    (anon / authenticated) have no access to these tables at all.
    """
    await session.execute(
        text("select set_config('app.user_id', :uid, true), set_config('role', 'datanest_api', true)"),
        {"uid": str(user_id)},
    )


async def get_db(user: AuthUser = Depends(get_current_user)) -> AsyncIterator[AsyncSession]:
    """User-scoped session. Commits on success, rolls back on error. `session.info['user_id']` is the internal id."""
    user_id = await resolve_user_id(user)
    assert _sessionmaker is not None
    async with _sessionmaker() as session:
        async with session.begin():
            await apply_rls_context(session, user_id, user.email)
            session.info["user_id"] = user_id
            yield session


async def dispose_engine() -> None:
    """Close every pooled connection (called on app shutdown so connections aren't left open on the database pooler)."""
    global _engine, _sessionmaker
    engine, _engine, _sessionmaker = _engine, None, None
    if engine is not None:
        await engine.dispose()
