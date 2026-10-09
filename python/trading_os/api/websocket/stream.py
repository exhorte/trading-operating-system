"""The cockpit's live stream (``/ws``): one frame per event, a snapshot first, a bounded queue per client.

The contract (``docs/architecture`` § 9):

* a server frame is ``{"type", "id", "occurredAt", "accountId", "correlationId", "payload"}``; the **first** is
  ``system.snapshot`` — the whole state, so a client that connects (or reconnects) never has to guess;
* by default a client receives every account; ``{"type": "subscribe", "accountIds": [...]}`` narrows it (events that belong to
  no account — the heartbeat, the calendar, the health — are always sent) and answers with a fresh, narrowed snapshot;
  ``{"type": "resync"}`` asks for a fresh snapshot;
* **back-pressure.** Each client has a bounded queue (500 frames). When it is full the oldest *telemetry* frame is dropped —
  a quote, an account snapshot: the next one supersedes it — and **never a lifecycle event** (an order acknowledged, a
  position closed, a halt). If the queue is full of lifecycle events the client is too slow to be trusted with a partial
  history: it is closed with 1013 and resynchronises from a snapshot when it comes back;
* the server never waits for a slow client: events are offered to every queue and the writer task of each client sends at its
  own pace.

What is counted (``stats``) is what the health reports: clients, frames sent, dropped, clients closed for overflow.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import WebSocket, WebSocketDisconnect

from trading_os.domain.events import CandleClosed
from trading_os.shared.events.base import Event
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.ids import new_id
from trading_os.shared.time import Clock, iso

logger = logging.getLogger(__name__)

CLIENT_QUEUE = 500
OVERFLOW_CLOSE = 1013  # « try again later »: reconnect, and resynchronise from a snapshot

SnapshotBuilder = Callable[[frozenset[str] | None], Awaitable[dict[str, Any]]]


class Sink(Protocol):
    """What a client's writer needs of a socket."""

    async def send_text(self, data: str) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


@dataclass(frozen=True)
class Frame:
    text: str  # already serialised: one dump per event, shared by every client
    account_id: str | None
    droppable: bool


@dataclass(frozen=True)
class HubStats:
    clients: int
    frames_sent: int
    frames_dropped: int
    closed_for_overflow: int


def is_droppable(event: Event) -> bool:
    """High-rate telemetry that the next frame supersedes. A closed candle is a fact, not telemetry, whatever its flag."""
    return not event.persist and not isinstance(event, CandleClosed)


class Client:
    def __init__(self, sink: Sink, *, capacity: int = CLIENT_QUEUE) -> None:
        self._sink = sink
        self._capacity = capacity
        self._queue: deque[Frame] = deque()
        self._wake = asyncio.Event()
        self.accounts: frozenset[str] | None = None  # None = every account
        self.sent = 0
        self.dropped = 0
        self.overflowed = False
        self.closed = False

    def wants(self, account_id: str | None) -> bool:
        return account_id is None or self.accounts is None or account_id in self.accounts

    @property
    def queued(self) -> int:
        return len(self._queue)

    def offer(self, frame: Frame) -> None:
        """Never blocks, never raises. Under pressure telemetry goes first; a lifecycle event that cannot be queued closes
        the client instead of being lost behind its back."""
        if self.closed or self.overflowed:
            return
        if len(self._queue) >= self._capacity and not self._drop_oldest_telemetry():
            if frame.droppable:
                self.dropped += 1
                return
            self.overflowed = True
            self._wake.set()
            return
        self._queue.append(frame)
        self._wake.set()

    def push_first(self, frame: Frame) -> None:
        """A snapshot goes to the front: whatever was queued while it was being built follows it."""
        if self.closed or self.overflowed:
            return
        self._queue.appendleft(frame)
        self._wake.set()

    def _drop_oldest_telemetry(self) -> bool:
        for index, queued in enumerate(self._queue):
            if queued.droppable:
                del self._queue[index]
                self.dropped += 1
                return True
        return False

    async def run(self) -> None:
        """The writer: sends at the client's own pace until it is closed, overflows or the socket fails."""
        try:
            while not self.closed:
                await self._wake.wait()
                self._wake.clear()
                while self._queue and not self.overflowed:
                    frame = self._queue.popleft()
                    await self._sink.send_text(frame.text)
                    self.sent += 1
                if self.overflowed:
                    await self._sink.close(OVERFLOW_CLOSE)
                    return
        except (WebSocketDisconnect, ConnectionError, RuntimeError, OSError):
            return  # the client went away: the read loop notices and unregisters it
        finally:
            self.closed = True


class _SocketSink:
    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket

    async def send_text(self, data: str) -> None:
        await self._websocket.send_text(data)

    async def close(self, code: int = 1000) -> None:
        with contextlib.suppress(RuntimeError, OSError):
            await self._websocket.close(code=code)


class CockpitStream:
    def __init__(self, snapshot: SnapshotBuilder, *, clock: Clock, capacity: int = CLIENT_QUEUE) -> None:
        self._snapshot = snapshot
        self._clock = clock
        self._capacity = capacity
        self._clients: set[Client] = set()
        self._retired_sent = 0
        self._retired_dropped = 0
        self._overflow_closed = 0

    # ------------------------------------------------------------------------------------------ wiring
    def subscribe(self, events: EventDispatcher) -> None:
        events.subscribe_all(self.on_event)

    def stats(self) -> HubStats:
        live = list(self._clients)
        return HubStats(
            clients=len(live),
            frames_sent=self._retired_sent + sum(c.sent for c in live),
            frames_dropped=self._retired_dropped + sum(c.dropped for c in live),
            closed_for_overflow=self._overflow_closed,
        )

    # ------------------------------------------------------------------------------------------ the stream
    async def on_event(self, event: Event) -> None:
        if not self._clients:
            return
        frame = Frame(
            text=json.dumps(event.to_wire(), separators=(",", ":")),
            account_id=event.account_id,
            droppable=is_droppable(event),
        )
        for client in tuple(self._clients):
            if client.wants(frame.account_id):
                client.offer(frame)

    def snapshot_frame(self, payload: dict[str, Any]) -> Frame:
        wire = {
            "type": "system.snapshot", "id": new_id("snap"), "occurredAt": iso(self._clock.now()),
            "accountId": None, "correlationId": None, "payload": payload,
        }  # fmt: skip
        return Frame(text=json.dumps(wire, separators=(",", ":"), default=str), account_id=None, droppable=False)

    async def serve(self, websocket: WebSocket) -> None:
        """One connection, from the handshake to the disconnection."""
        await websocket.accept()
        client = Client(_SocketSink(websocket), capacity=self._capacity)
        self._clients.add(client)  # registered first: what happens while the snapshot is built is queued behind it
        writer = asyncio.create_task(client.run(), name="ws-writer")
        try:
            client.push_first(self.snapshot_frame(await self._snapshot(client.accounts)))
            while not client.closed:
                message = await websocket.receive_text()
                await self._on_message(client, message)
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("websocket client failed")
            with contextlib.suppress(RuntimeError, OSError):
                await websocket.close(code=1011)
        finally:
            self._retire(client)
            writer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await writer

    def _retire(self, client: Client) -> None:
        if client in self._clients:
            self._clients.discard(client)
            self._retired_sent += client.sent
            self._retired_dropped += client.dropped
            if client.overflowed:
                self._overflow_closed += 1

    async def _on_message(self, client: Client, text: str) -> None:
        try:
            message = json.loads(text)
        except ValueError:
            return  # not JSON: ignored, never fatal
        kind = message.get("type") if isinstance(message, dict) else None
        if kind == "subscribe":
            ids = message.get("accountIds")
            client.accounts = frozenset(str(i) for i in ids) if isinstance(ids, list) else None
        elif kind != "resync":
            return
        client.push_first(self.snapshot_frame(await self._snapshot(client.accounts)))
