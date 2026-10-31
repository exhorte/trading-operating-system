"""In-process publish/subscribe. A handler failing never breaks the publisher or the other handlers."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from trading_os.shared.events.base import Event

logger = logging.getLogger(__name__)

Handler = Callable[[Any], Awaitable[None] | None]


class EventDispatcher:
    def __init__(self) -> None:
        self._by_type: dict[type[Event], list[Handler]] = {}
        self._all: list[Handler] = []
        self.published = 0
        self.handler_errors = 0

    def subscribe(self, event_type: type[Event], handler: Handler) -> None:
        self._by_type.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: Handler) -> None:
        self._all.append(handler)

    async def publish(self, event: Event) -> None:
        self.published += 1
        handlers: list[Handler] = [*self._all]
        for event_type, registered in self._by_type.items():
            if isinstance(event, event_type):
                handlers.extend(registered)
        for handler in handlers:
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                self.handler_errors += 1
                logger.exception("event handler failed for %s", event.wire_type)
