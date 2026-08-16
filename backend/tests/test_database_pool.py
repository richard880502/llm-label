"""Regression test for the connection-pool-exhaustion incident.

Before the fix, every router did `conn = get_db(); ...; conn.close()` with no
try/finally. Any exception raised between acquire and close (a bad query, a
validation error, a cancellation) meant `pool.putconn()` was never called, so
the connection was permanently lost from the pool. Enough of these events
exhausted the pool and `/api/projects` started failing with
`psycopg_pool.PoolTimeout`.

This test drives more failures through `get_db()` than the pool has
connections, and asserts the pool is still fully available afterward.
"""

import psycopg
import pytest

from ..database import _get_pool, get_db


def _pool_reachable() -> bool:
    try:
        with _get_pool().connection(timeout=3):
            return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _pool_reachable(),
    reason="requires a reachable Postgres (see docker-compose.yml, DATABASE_URL)",
)


class _Boom(Exception):
    pass


def test_connection_is_returned_to_pool_on_exception():
    pool = _get_pool()
    baseline = pool.get_stats()["pool_available"]

    # Drive more failures than the pool has connections. If any single one
    # leaked, later iterations would eventually block on pool.getconn() and
    # raise PoolTimeout instead of Boom.
    for _ in range(pool.max_size + 5):
        with pytest.raises(_Boom):
            with get_db() as conn:
                conn.execute("SELECT 1")
                raise _Boom("simulated failure mid-request")

    assert pool.get_stats()["pool_available"] == baseline


def test_pool_still_serves_requests_after_repeated_errors():
    pool = _get_pool()

    for _ in range(pool.max_size + 5):
        with pytest.raises(_Boom):
            with get_db() as conn:
                raise _Boom("simulated failure mid-request")

    with get_db() as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
