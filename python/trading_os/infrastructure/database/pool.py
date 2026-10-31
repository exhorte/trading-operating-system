"""The database: one async connection pool, explicit SQL, no ORM.

Rules this module holds for everything above it:

* **Fail closed.** A query that cannot reach the database raises ``Unavailable("database_unavailable")`` — callers that
  must persist *before* acting (commands, risk decisions, lockouts) let it propagate and refuse; only telemetry (ticks)
  is allowed to be lossy, and counts what it loses.
* Every session runs in UTC, so ``timestamptz`` always comes back as an aware UTC ``datetime``.
* Rows are dicts; ``jsonb`` columns come back as Python objects and are written through ``Jsonb``.
* The pool reconnects by itself: an outage does not need a restart (``health`` says whether we are up *now*).

psycopg's async mode cannot run on Windows' default Proactor event loop: the process entry point (``cli serve``) and the
test configuration both select the Selector loop, and nothing in this package spawns asyncio subprocesses.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, LiteralString

import psycopg
from psycopg import AsyncConnection, sql
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from trading_os.shared.errors import Unavailable
from trading_os.shared.logging.redaction import redact
from trading_os.shared.time import utcnow

logger = logging.getLogger(__name__)

Row = dict[str, Any]
# Literal text only: an f-string or a concatenation of runtime values is a type error (SQL injection guard).
Query = LiteralString | bytes | sql.SQL | sql.Composed
Params = Sequence[Any] | Mapping[str, Any] | None


@dataclass
class DatabaseHealth:
    up: bool = False
    last_error: str | None = None
    last_ok_at: datetime | None = None
    last_error_at: datetime | None = None


def jsonb(value: Any) -> Jsonb:
    """A value for a ``jsonb`` column. Pydantic models are dumped the way the API shows them (camelCase)."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    elif isinstance(value, list):
        value = [v.model_dump(mode="json", by_alias=True) if hasattr(v, "model_dump") else v for v in value]
    return Jsonb(value)


class Database:
    def __init__(self, url: str, *, min_size: int = 1, max_size: int = 8, connect_timeout: float = 5.0) -> None:
        self._url = url
        self._pool: AsyncConnectionPool[AsyncConnection[DictRow]] | None = None
        self._min_size = min_size
        self._max_size = max_size
        self._connect_timeout = connect_timeout
        self.health = DatabaseHealth()

    # ------------------------------------------------------------------------------------------ lifecycle
    async def open(self) -> None:
        if self._pool is not None:
            return
        self._pool = AsyncConnectionPool(
            self._url,
            min_size=self._min_size,
            max_size=self._max_size,
            open=False,
            timeout=self._connect_timeout,
            reconnect_timeout=30.0,
            kwargs={
                "row_factory": dict_row,
                "options": "-c timezone=UTC",
                "connect_timeout": int(self._connect_timeout),
            },
            check=AsyncConnectionPool.check_connection,
            name="trading-os",
        )
        await self._pool.open(wait=False)

    async def close(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            await pool.close(timeout=5)
        self.health.up = False

    @property
    def is_open(self) -> bool:
        return self._pool is not None

    # ------------------------------------------------------------------------------------------ access
    def _require(self) -> AsyncConnectionPool[AsyncConnection[DictRow]]:
        if self._pool is None:
            raise Unavailable("database is not open", code="database_unavailable")
        return self._pool

    def _failed(self, error: Exception) -> Unavailable:
        message = redact(str(error)).splitlines()[0][:200] if str(error) else type(error).__name__
        self.health.up = False
        self.health.last_error = message
        self.health.last_error_at = utcnow()
        return Unavailable(f"database unavailable: {message}", code="database_unavailable")

    def _ok(self) -> None:
        self.health.up = True
        self.health.last_error = None
        self.health.last_ok_at = utcnow()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[DictRow]]:
        """A pooled connection in autocommit-off mode: use ``transaction()`` when several statements must be atomic."""
        pool = self._require()
        try:
            async with pool.connection() as conn:
                yield conn
            self._ok()
        except (psycopg.OperationalError, PoolTimeout) as error:
            raise self._failed(error) from error

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection[DictRow]]:
        """Statements inside commit together or not at all."""
        async with self.connection() as conn, conn.transaction():
            yield conn

    async def fetch_all(self, sql: Query, params: Params = None) -> list[Row]:
        async with self.connection() as conn:
            cursor = await conn.execute(sql, params)
            return list(await cursor.fetchall())

    async def fetch_one(self, sql: Query, params: Params = None) -> Row | None:
        async with self.connection() as conn:
            cursor = await conn.execute(sql, params)
            return await cursor.fetchone()

    async def fetch_value(self, sql: Query, params: Params = None) -> Any:
        row = await self.fetch_one(sql, params)
        return None if row is None else next(iter(row.values()))

    async def execute(self, sql: Query, params: Params = None) -> int:
        async with self.connection() as conn:
            cursor = await conn.execute(sql, params)
            return cursor.rowcount

    async def execute_many(self, sql: Query, rows: Sequence[Sequence[Any] | Mapping[str, Any]]) -> None:
        if not rows:
            return
        async with self.connection() as conn, conn.cursor() as cursor:
            await cursor.executemany(sql, rows)

    # ------------------------------------------------------------------------------------------ health
    async def ping(self) -> bool:
        """True when a round trip works right now. Never raises; updates ``health``."""
        try:
            await self.fetch_value("SELECT 1")
        except Unavailable:
            return False
        return True
