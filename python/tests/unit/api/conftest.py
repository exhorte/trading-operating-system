"""Fixtures of the API tests: a harness over a fresh database, and the application over a ready core (one connected account, one
execution agent, the autonomy ladder at OBSERVE). A test that needs another rung opens its own with ``open_api``."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from tests.support.api import Api, open_api
from tests.support.harness import Harness
from trading_os.infrastructure.database.pool import Database


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


@pytest.fixture
async def api(h: Harness) -> AsyncIterator[Api]:
    async with open_api(h) as instance:
        yield instance
