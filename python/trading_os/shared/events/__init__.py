"""Event model and in-process dispatcher. No distributed bus: services publish, three generic subscribers
(event store, WebSocket stream, logger) listen. Concrete events live in ``trading_os.domain.events``."""

from trading_os.shared.events.base import EVENT_REGISTRY, Event
from trading_os.shared.events.dispatcher import EventDispatcher

__all__ = ["EVENT_REGISTRY", "Event", "EventDispatcher"]
