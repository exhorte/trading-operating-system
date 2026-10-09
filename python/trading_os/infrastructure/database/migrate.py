"""Numbered, checksummed, transactional migrations — the schema is never replayed at start, only the pending migrations are applied.

* Files are ``migrations/NNNN_name.sql``, applied in order, each in its own transaction, recorded in ``schema_migrations``
  with a SHA-256 of the file. A file edited after it was applied is an error, not a silent drift.
* ``0001_baseline`` is the previous schema **verbatim and idempotent**: against the existing database it creates nothing and
  the database is simply recognised (the data of the user stays where it is).
* Only additive migrations live here. A destructive change is a script in ``migrations/manual/`` that nothing ever runs by
  itself (``python -m trading_os db manual <name>`` after a human decision).
* One migrator at a time (advisory lock), so two processes starting together cannot interleave.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from importlib import resources

import psycopg

from trading_os.shared.errors import TradingOsError, Unavailable
from trading_os.shared.logging.redaction import redact

logger = logging.getLogger(__name__)

PACKAGE = "trading_os.infrastructure.database"
ADVISORY_LOCK_KEY = 7_274_001  # arbitrary, fixed: « TOS » + 1
_FILE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


class MigrationError(TradingOsError):
    code = "migration_error"
    http_status = 500


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MigrationStatus:
    version: str
    name: str
    applied: bool
    applied_checksum: str | None
    checksum: str

    @property
    def drifted(self) -> bool:
        return self.applied and self.applied_checksum != self.checksum


def discover() -> list[Migration]:
    folder = resources.files(PACKAGE).joinpath("migrations")
    found: list[Migration] = []
    for entry in folder.iterdir():
        match = _FILE.match(entry.name)
        if match:
            # normalise line endings: a checkout with CRLF must hash like one with LF
            text = entry.read_text(encoding="utf-8").replace("\r\n", "\n")
            found.append(Migration(version=match.group(1), name=match.group(2), sql=text))
    found.sort(key=lambda m: m.version)
    versions = [m.version for m in found]
    if len(set(versions)) != len(versions):
        raise MigrationError(f"duplicate migration numbers: {versions}")
    return found


def discover_manual() -> dict[str, str]:
    folder = resources.files(PACKAGE).joinpath("migrations").joinpath("manual")
    return {
        e.name.removesuffix(".sql"): e.read_text(encoding="utf-8").replace("\r\n", "\n")
        for e in folder.iterdir()
        if e.name.endswith(".sql")
    }


_BOOKKEEPING = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text PRIMARY KEY,
    name       text NOT NULL,
    checksum   text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


async def _connect(url: str) -> psycopg.AsyncConnection[tuple[object, ...]]:
    try:
        return await psycopg.AsyncConnection.connect(url, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as error:
        message = redact(str(error)).splitlines()[0][:200]
        raise Unavailable(f"database unavailable: {message}", code="database_unavailable") from error


async def status(url: str) -> list[MigrationStatus]:
    migrations = discover()
    conn = await _connect(url)
    try:
        exists = await (await conn.execute("SELECT to_regclass('public.schema_migrations') IS NOT NULL")).fetchone()
        applied: dict[str, str] = {}
        if exists and exists[0]:
            rows = await (await conn.execute("SELECT version, checksum FROM schema_migrations")).fetchall()
            applied = {str(r[0]): str(r[1]) for r in rows}
    finally:
        await conn.close()
    return [
        MigrationStatus(m.version, m.name, m.version in applied, applied.get(m.version), m.checksum) for m in migrations
    ]


async def migrate(url: str, *, target: str | None = None) -> list[str]:
    """Apply every pending migration (up to ``target`` if given). Returns the versions applied by this call."""
    migrations = discover()
    conn = await _connect(url)
    done: list[str] = []
    try:
        await conn.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        try:
            await conn.execute(_BOOKKEEPING)
            rows = await (await conn.execute("SELECT version, checksum FROM schema_migrations")).fetchall()
            applied = {str(r[0]): str(r[1]) for r in rows}
            for migration in migrations:
                if target is not None and migration.version > target:
                    break
                if migration.version in applied:
                    if applied[migration.version] != migration.checksum:
                        raise MigrationError(
                            f"migration {migration.version}_{migration.name} was modified after it was applied "
                            "(add a new migration instead of editing an applied one)"
                        )
                    continue
                logger.info("applying migration %s_%s", migration.version, migration.name)
                try:
                    async with conn.transaction():
                        await conn.execute(migration.sql.encode("utf-8"))
                        await conn.execute(
                            "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                            (migration.version, migration.name, migration.checksum),
                        )
                except psycopg.Error as error:
                    raise MigrationError(
                        f"migration {migration.version}_{migration.name} failed: {redact(str(error))}"
                    ) from error
                done.append(migration.version)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
    finally:
        await conn.close()
    return done


async def run_manual(url: str, name: str) -> None:
    """Run one destructive script from ``migrations/manual/``. Only ever called by a human, through the CLI."""
    scripts = discover_manual()
    if name not in scripts:
        raise MigrationError(f"no manual script {name!r} (available: {', '.join(sorted(scripts)) or 'none'})")
    conn = await _connect(url)
    try:
        async with conn.transaction():
            await conn.execute(scripts[name].encode("utf-8"))
    except psycopg.Error as error:
        raise MigrationError(f"manual script {name} failed: {redact(str(error))}") from error
    finally:
        await conn.close()
