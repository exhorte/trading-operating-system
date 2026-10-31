"""The FastAPI application: ``create_app`` wires the access guard, CORS, the error envelope, the routers, the live stream and the
engine's life cycle onto a container.

* Middleware order matters: **CORS is outermost** (a preflight is answered before it is judged, and a refusal still carries
  the headers a browser needs to *read* it), the access guard inside it.
* The HTTP docs pages are off; the OpenAPI schema is served under ``/api`` — so it is guarded like everything else — and
  generated in-process for the cockpit's types (``app.openapi()``).
* The engine (database, recovery, agent socket, jobs) starts with the application and stops with it. Tests hand in a prepared
  container and ``start_engine=False``: they drive the cycles by hand.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from trading_os import __version__
from trading_os.api.errors import document_error_envelope, install_error_handlers
from trading_os.api.routes import accounts, autonomy, execution, journal, market, risk, strategy, system
from trading_os.api.security import AccessGuardMiddleware
from trading_os.api.websocket.snapshot import build_snapshot
from trading_os.api.websocket.stream import CockpitStream
from trading_os.app.config import Settings, get_settings
from trading_os.app.container import Container, build_container
from trading_os.runtime.engine import Engine


def _operation_id(route: APIRoute) -> str:
    """``accounts_connect`` rather than ``connect_api_accounts__account_id__connect_post``: stable, readable generated names — the
    tag first, then the function's name without a word that only repeats the tag (``list_accounts`` → ``accounts_list``)."""
    if not route.tags:
        return route.name
    tag = str(route.tags[0])
    words = [word for word in route.name.split("_") if word.rstrip("s") != tag.rstrip("s")]
    return "_".join([tag, *words])


def create_app(
    settings: Settings | None = None, *, container: Container | None = None, start_engine: bool = True
) -> FastAPI:
    settings = settings or get_settings()
    own_container = container is None
    container = container or build_container(settings)
    migrate_url = settings.database_url.get_secret_value() if own_container and settings.database_url else None
    engine = Engine(container, migrate_url=migrate_url)
    stream = CockpitStream(lambda accounts: build_snapshot(container, accounts), clock=container.clock)
    stream.subscribe(container.events)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if start_engine:
            await engine.start()
        try:
            yield
        finally:
            if start_engine:
                await engine.stop()

    app = FastAPI(
        title="Trading OS core",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
    )
    app.state.container = container
    app.state.engine = engine
    app.state.stream = stream
    install_error_handlers(app)
    document_error_envelope(app)

    token = settings.trading_os_cockpit_token
    app.add_middleware(
        AccessGuardMiddleware, token=token.get_secret_value() if token else None, origins=settings.origins
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["authorization", "content-type"],
        max_age=600,
    )

    for router in (
        system.router, accounts.router, accounts.active_router, autonomy.router, risk.router, execution.router,
        market.router, journal.router, strategy.router,
    ):  # fmt: skip
        app.include_router(router)

    @app.websocket("/ws")
    async def live(websocket: WebSocket) -> None:
        await stream.serve(websocket)

    return app
