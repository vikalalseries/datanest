import pytest


@pytest.fixture(autouse=True, scope="module")
def _fresh_db_engine():
    """Each integration module runs its own TestClient/event loop. Drop the cached engine so a new one is
    created on the current loop (a pooled connection from a previous, closed loop can't be reused)."""
    from app.database import connection

    connection._engine = None
    connection._sessionmaker = None
    connection._uid_cache.clear()
    yield
    connection._engine = None
    connection._sessionmaker = None
