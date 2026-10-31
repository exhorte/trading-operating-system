"""FastAPI dependencies: how a route reaches the services. The container is built once (``create_app``) and kept on the
application; a route asks for it, or for the one service it needs, and never builds anything itself."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from trading_os.app.container import Container


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


Core = Annotated[Container, Depends(get_container)]
