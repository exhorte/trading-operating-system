"""Shared fixtures. Tests never read the developer's real ``.env`` and never touch the real database."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Any

import pytest

from tests.support.postgres import NoPostgres, Server, postgres_server, unique_name
from trading_os.infrastructure.database.migrate import migrate
from trading_os.infrastructure.database.pool import Database
from trading_os.shared.logging.redaction import clear_secrets


def pytest_asyncio_loop_factories(config: pytest.Config, item: pytest.Item) -> Mapping[str, Any]:
    """psycopg's async mode cannot run on Windows' default Proactor loop; nothing in the core needs a Proactor-only
    feature (the MT5 worker is driven through threads), so every async test runs on the Selector loop."""
    return {"selector": asyncio.SelectorEventLoop}


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in list(os.environ):
        if name.startswith("MT5_PASSWORD_") or name in {
            "DATABASE_URL",
            "FRED_API_KEY",
            "TRADING_MODE",
            "ACTIVE_ACCOUNT_ID",
            "CREDENTIAL_STORE",
            "MT5_ENABLED",
            "TRADINGOS_COCKPIT_TOKEN",
            "TRADINGOS_AGENT_TOKEN",
        }:
            monkeypatch.delenv(name, raising=False)
    clear_secrets()
    yield
    clear_secrets()


# ---------------------------------------------------------------------------------------------------- PostgreSQL


@pytest.fixture(scope="session")
def pg_server() -> Iterator[Server]:
    try:
        with postgres_server() as server:
            yield server
    except NoPostgres as error:
        pytest.fail(str(error), pytrace=False)  # a database test never "passes" or "skips" without a database


@pytest.fixture(scope="session")
def template_database(pg_server: Server) -> Iterator[str]:
    """One database, migrated once; each test gets a cheap clone of it."""
    name = unique_name("tradingos_tpl")
    url = pg_server.create_database(name)
    try:
        asyncio.run(migrate(url), loop_factory=asyncio.SelectorEventLoop)
        yield name
    finally:
        pg_server.drop_database(name)


@pytest.fixture(scope="session")
def shared_database_url(pg_server: Server, template_database: str) -> Iterator[str]:
    """The database most tests use: created once, emptied (not recreated) before each test."""
    name = unique_name("tradingos_shared")
    url = pg_server.create_database(name, template=template_database)
    try:
        yield url
    finally:
        pg_server.drop_database(name)


@pytest.fixture
def fresh_database_url(pg_server: Server, template_database: str) -> Iterator[str]:
    """A private, freshly migrated database for the tests that change the schema bookkeeping itself."""
    name = unique_name()
    url = pg_server.create_database(name, template=template_database)
    try:
        yield url
    finally:
        pg_server.drop_database(name)


_EMPTY_EVERY_TABLE = """
DO $$
DECLARE tables text;
BEGIN
    SELECT string_agg(format('%I', tablename), ', ') INTO tables
    FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'schema_migrations';
    EXECUTE 'TRUNCATE TABLE ' || tables || ' RESTART IDENTITY CASCADE';
END
$$
"""


@pytest.fixture
async def db(shared_database_url: str) -> AsyncIterator[Database]:
    database = Database(shared_database_url, min_size=1, max_size=4)
    await database.open()
    await database.execute(_EMPTY_EVERY_TABLE)
    try:
        yield database
    finally:
        await database.close()
