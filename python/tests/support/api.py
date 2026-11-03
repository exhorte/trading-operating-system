"""The API in a test: the real application over a whole test core, an in-memory HTTP client that already carries the cockpit's
token and Origin (``Api.bare`` is the one that does not)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import SecretStr

from tests.support.core import Core, make_ready_core
from tests.support.harness import Harness
from trading_os.app.main import create_app
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.infrastructure.security.credentials import CredentialStore

TOKEN = "test-cockpit-token-0123456789abcdef"
ORIGIN = "http://localhost:3000"
HEADERS = {"Origin": ORIGIN, "Authorization": f"Bearer {TOKEN}"}
BASE = "http://127.0.0.1:8000"


@dataclass
class Api:
    core: Core
    app: FastAPI
    client: httpx.AsyncClient

    def bare(self) -> httpx.AsyncClient:
        """A client with no credentials at all."""
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False), base_url=BASE)

    async def get(self, path: str, **params: Any) -> httpx.Response:
        return await self.client.get(path, params={k: v for k, v in params.items() if v is not None})

    async def post(self, path: str, body: Any = None, **params: Any) -> httpx.Response:
        return await self.client.post(path, json=body, params={k: v for k, v in params.items() if v is not None})

    async def put(self, path: str, body: Any = None) -> httpx.Response:
        return await self.client.put(path, json=body)

    async def close(self) -> None:
        await self.client.aclose()


def new_account(login: int = 1_000_002, **extra: Any) -> dict[str, Any]:
    return {
        "name": "Second demo", "provider": "EXNESS", "accountType": "DIRECT", "login": login,
        "server": "Exness-MT5Trial", "environment": "DEMO", "referenceBalance": 10_000,
        "terminalPath": f"C:/MT5/exness-{login}", **extra,
    }  # fmt: skip


async def detach_first(api: Api) -> None:
    """Only one account is connected at a time (ADR 0021): a test that wants another one detaches the first."""
    assert api.core.account is not None
    response = await api.post(f"/api/accounts/{api.core.account.id}/disconnect", force="true")
    assert response.status_code == 200, response.text


async def create_second(api: Api, login: int = 1_000_002) -> dict[str, Any]:
    response = await api.post("/api/accounts", new_account(login))
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def quoted(api: Api, bid: float = 1.08492, ask: float = 1.08500) -> None:
    """Pin the simulated EURUSDm quote (the default one drifts with the clock) and let the core read it."""
    assert api.core.account is not None
    api.core.terminal.set_quote("EURUSDm", bid, ask)
    await api.core.c.market.poll_ticks(api.core.account.id)


def review_body(api: Api, **changes: Any) -> dict[str, Any]:
    assert api.core.account is not None
    body: dict[str, Any] = {
        "accountId": api.core.account.id, "symbol": "EURUSDm", "side": "buy",
        "entryPrice": 1.0850, "stopLoss": 1.0840, "takeProfit": 1.0880,
    }  # fmt: skip
    body.update(changes)
    return body


async def make_api(
    h: Harness,
    *,
    top: AutonomyMode = AutonomyMode.OBSERVE,
    credentials: CredentialStore | None = None,
    calendar: bool = True,
) -> Api:
    """A ready core (one connected account, one agent, a synced, quiet news calendar, a few cycles behind it) behind the
    real application."""
    core = await make_ready_core(h, top=top, credentials=credentials, calendar=calendar)
    core.c.settings.trading_os_cockpit_token = SecretStr(TOKEN)  # (read by alias only: assigned after construction)
    app = create_app(core.c.settings, container=core.c, start_engine=False)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url=BASE, headers=HEADERS
    )
    return Api(core=core, app=app, client=client)


@asynccontextmanager
async def open_api(
    h: Harness,
    *,
    top: AutonomyMode = AutonomyMode.OBSERVE,
    credentials: CredentialStore | None = None,
    calendar: bool = True,
) -> AsyncIterator[Api]:
    """``make_api`` that cleans up after itself."""
    api = await make_api(h, top=top, credentials=credentials, calendar=calendar)
    try:
        yield api
    finally:
        await api.close()


@asynccontextmanager
async def serving(app: FastAPI) -> AsyncIterator[int]:
    """Run the application on a real loopback socket (port chosen by the system) inside the test's own event loop — the
    only way to exercise a real WebSocket handshake against the async database pool that lives in that loop."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off", loop="none")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        if task.done():
            task.result()
        await asyncio.sleep(0.01)
    port = int(server.servers[0].sockets[0].getsockname()[1])
    try:
        yield port
    finally:
        server.should_exit = True
        await task
