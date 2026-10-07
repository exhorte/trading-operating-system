"""TCP server for the MT5 execution agent (EA-05, ADR 0010) — the Python replacement of the C# ``Mt5AgentServer``.

The agent dials *in* (plain TCP, newline-delimited JSON, never WSS: the connection is loopback-only between two
processes of one personal machine). This is not a bridge: the EA can reach the core only through a socket, and this is
that socket.

Registry: **one registration per login**, owned by the connection whose ``agent.hello`` made it. A closing connection only
ever removes its *own* registration. A second hello for a login whose agent is alive is refused and its connection closed
(ADR 0010: one agent per environment); a connection silent for longer than ``stale_after`` is a dead agent (terminal crash,
half-open TCP): the watchdog closes it and a new hello replaces it at once.

Security (I0/I1): the hello must carry the agent token (the agent reads it from ``MQL5\\Files``); none configured here means
**every** agent is refused (fail closed). The comparison is constant-time and the token is never kept: ``decode_line`` hands
it back separately and no model has a field for it. Agents that announce the ``ping`` capability get a ``control.ping``
every ``ping_interval`` — the core's liveness beat, on which the agent's dead-man switch relies.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import time
from typing import Protocol

from trading_os.domain.execution.agent import AgentStatus
from trading_os.infrastructure.mt5.wire import (
    AgentHeartbeat,
    AgentHello,
    ExecutionAck,
    ExecutionReconciled,
    ExecutionReport,
    PositionScan,
    decode_line,
    halt_line,
    ping_line,
)
from trading_os.shared.time import Clock, SystemClock, to_epoch_ms

logger = logging.getLogger(__name__)

MAX_LINE_BYTES = 1 << 20


def build_status(hello: AgentHello, beat: AgentHeartbeat | None) -> AgentStatus:
    """The agent as it describes itself: its hello, overlaid by its latest heartbeat for what can change while connected."""
    return AgentStatus(
        account_login=hello.account_id,
        agent_id=hello.agent_id,
        agent_version=hello.agent_version,
        build_id=hello.build_id,
        mode=(beat.mode if beat and beat.mode else hello.mode),
        mode_ceiling=hello.mode_ceiling,
        identity=(beat.identity if beat and beat.identity else hello.identity),
        expected_account_id=hello.expected_account_id,
        broker=hello.broker or None,
        server=hello.server,
        currency=hello.currency,
        trade_mode=hello.trade_mode,
        margin_mode=hello.margin_mode,
        fifo_close=hello.fifo_close,
        leverage=hello.leverage,
        terminal_trade_allowed=_first(beat.terminal_trade_allowed if beat else None, hello.terminal_trade_allowed),
        expert_trade_allowed=_first(beat.expert_trade_allowed if beat else None, hello.expert_trade_allowed),
        account_trade_expert=_first(beat.account_trade_expert if beat else None, hello.account_trade_expert),
        account_trade_allowed=_first(beat.account_trade_allowed if beat else None, hello.account_trade_allowed),
        tradable=hello.tradable,
        closable=hello.closable,
        halted=_first(beat.halted if beat else None, hello.halted),
        attached_experts=list(
            (beat.attached_experts if beat and beat.attached_experts is not None else hello.attached_experts) or []
        ),
        capabilities=list(hello.capabilities or []),
        gateway_silent_ms=beat.gateway_silent_ms if beat else None,
        last_heartbeat_ms=beat.time if beat else None,
    )


def _first(*values: bool | None) -> bool | None:
    for value in values:
        if value is not None:
            return value
    return None


class EaLinkHandler(Protocol):
    """What the core wants to know about its agents. Implemented by the execution service."""

    async def on_registered(self, status: AgentStatus) -> None: ...
    async def on_unregistered(self, login: str) -> None: ...
    async def on_status_changed(self, status: AgentStatus) -> None: ...
    async def on_heartbeat(self, login: str, beat: AgentHeartbeat) -> None: ...
    async def on_ack(self, login: str, ack: ExecutionAck) -> None: ...
    async def on_report(self, login: str, report: ExecutionReport) -> None: ...
    async def on_reconciled(self, login: str, reconciled: ExecutionReconciled) -> None: ...
    async def on_position_scan(self, login: str, scan: PositionScan) -> None: ...
    async def on_refused(self, agent_id: str, reason: str) -> None: ...
    async def on_duplicate_refused(self, agent_id: str) -> None: ...


class NullHandler:
    """Base for handlers that only care about some callbacks."""

    async def on_registered(self, status: AgentStatus) -> None: ...
    async def on_unregistered(self, login: str) -> None: ...
    async def on_status_changed(self, status: AgentStatus) -> None: ...
    async def on_heartbeat(self, login: str, beat: AgentHeartbeat) -> None: ...
    async def on_ack(self, login: str, ack: ExecutionAck) -> None: ...
    async def on_report(self, login: str, report: ExecutionReport) -> None: ...
    async def on_reconciled(self, login: str, reconciled: ExecutionReconciled) -> None: ...
    async def on_position_scan(self, login: str, scan: PositionScan) -> None: ...
    async def on_refused(self, agent_id: str, reason: str) -> None: ...
    async def on_duplicate_refused(self, agent_id: str) -> None: ...


class _Connection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.last_seen = time.monotonic()
        self.login: str | None = None
        self.hello: AgentHello | None = None
        self.beat: AgentHeartbeat | None = None
        self.published: AgentStatus | None = None
        self.write_lock = asyncio.Lock()  # concurrent senders must not interleave lines
        self.closed = False

    def touch(self) -> None:
        self.last_seen = time.monotonic()

    def silent_for(self, seconds: float) -> bool:
        return time.monotonic() - self.last_seen > seconds

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            with contextlib.suppress(Exception):
                self.writer.close()

    def can(self, capability: str) -> bool:
        return self.hello is not None and capability in (self.hello.capabilities or [])


class EaLinkServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        token: str | None,
        handler: EaLinkHandler,
        clock: Clock | None = None,
        stale_after: float = 30.0,
        ping_interval: float = 5.0,
        write_timeout: float = 5.0,
    ) -> None:
        self._host, self._port = host, port
        self._token = token or ""
        self._handler = handler
        self._clock = clock or SystemClock()
        self._stale_after = stale_after
        self._ping_interval = ping_interval
        self._write_timeout = write_timeout
        self._server: asyncio.Server | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._by_login: dict[str, _Connection] = {}
        self._open: set[_Connection] = set()
        self.frames_received = 0
        self.frames_dropped = 0

    # --- lifecycle ----------------------------------------------------------------------------------------------

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._serve, self._host, self._port, limit=MAX_LINE_BYTES)
        self._port = self._server.sockets[0].getsockname()[1]
        self._tasks = [asyncio.create_task(self._watchdog()), asyncio.create_task(self._ping_loop())]
        return self._port

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        for connection in list(self._open):
            connection.close()
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), timeout=2)
            self._server = None

    @property
    def port(self) -> int:
        return self._port

    # --- registry (read side) ---------------------------------------------------------------------------------

    def registered_logins(self) -> list[str]:
        return sorted(self._by_login)

    def is_connected(self, login: str | None = None) -> bool:
        return bool(self._by_login) if login is None else login in self._by_login

    def status(self, login: str) -> AgentStatus | None:
        connection = self._by_login.get(login)
        if connection is None or connection.hello is None:
            return None
        return build_status(connection.hello, connection.beat)

    # --- commands to the agent -----------------------------------------------------------------------------------

    async def send_line(self, login: str, line: bytes) -> bool:
        """Deliver one prepared line. False when no agent is registered for the login or the write failed —
        the caller must treat that as AGENT_UNREACHABLE, never as a silent no-op."""
        connection = self._by_login.get(login)
        return connection is not None and await self._write(connection, line)

    async def send_halt(self, login: str, reason: str) -> bool:
        """Ask the agent to set its local halt. It can only be *set* from here — lifting it takes a human on the chart."""
        connection = self._by_login.get(login)
        if connection is None or not connection.can("halt"):
            return False
        return await self._write(connection, halt_line(reason, to_epoch_ms(self._clock.now())))

    async def _write(self, connection: _Connection, line: bytes) -> bool:
        if connection.closed:
            return False
        async with connection.write_lock:
            try:
                connection.writer.write(line)
                await asyncio.wait_for(connection.writer.drain(), timeout=self._write_timeout)
                return True
            except (TimeoutError, ConnectionError, OSError, RuntimeError):
                connection.close()
                return False

    # --- background loops ----------------------------------------------------------------------------------------

    async def _watchdog(self) -> None:
        period = min(self._stale_after / 2, 5.0)
        while True:
            await asyncio.sleep(period)
            for connection in [c for c in self._open if c.silent_for(self._stale_after)]:
                connection.close()  # its read loop ends; _serve unregisters it

    async def _ping_loop(self) -> None:
        while True:
            await asyncio.sleep(self._ping_interval)
            line = ping_line(to_epoch_ms(self._clock.now()))
            for connection in [c for c in self._by_login.values() if c.can("ping")]:
                await self._write(connection, line)

    # --- one connection ------------------------------------------------------------------------------------------

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connection = _Connection(reader, writer)
        self._open.add(connection)
        try:
            while not connection.closed:
                raw = await reader.readline()
                if not raw:
                    break  # the agent closed the connection
                connection.touch()
                line = raw.decode("utf-8-sig", errors="replace").strip()
                if line:
                    await self._handle(line, connection)
        except (ConnectionError, OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError):
            pass  # malformed stream or dropped connection: close and let the agent reconnect — never crash the core
        except asyncio.CancelledError:
            raise
        finally:
            self._open.discard(connection)
            removed = connection.login is not None and self._by_login.get(connection.login) is connection
            login = connection.login
            if removed and login is not None:
                del self._by_login[login]
            connection.close()
            if removed and login is not None:
                await self._safely(self._handler.on_unregistered(login))

    async def _handle(self, line: str, connection: _Connection) -> None:
        self.frames_received += 1
        frame = decode_line(line)
        message = frame.message
        if message is None:
            self.frames_dropped += 1
            return  # unreadable or not consumed here: dropped, never a crash

        if isinstance(message, AgentHello):
            await self._on_hello(message, frame.token, connection)
            return

        login = connection.login
        if login is None or self._by_login.get(login) is not connection:
            self.frames_dropped += 1
            return  # nothing counts before a registered hello
        if isinstance(message, AgentHeartbeat):
            connection.beat = message
            hello = connection.hello
            assert hello is not None
            status = build_status(hello, message)
            changed = connection.published is None or not status.same_state_as(connection.published)
            if changed:
                connection.published = status
            await self._safely(self._handler.on_heartbeat(login, message))
            if changed:
                await self._safely(self._handler.on_status_changed(status))
        elif isinstance(message, ExecutionAck):
            await self._safely(self._handler.on_ack(login, message))
        elif isinstance(message, ExecutionReport):
            await self._safely(self._handler.on_report(login, message))
        elif isinstance(message, ExecutionReconciled):
            await self._safely(self._handler.on_reconciled(login, message))
        elif isinstance(message, PositionScan):
            await self._safely(self._handler.on_position_scan(login, message))

    def _token_refusal(self, presented: str | None) -> str | None:
        """None when the hello carries the configured token; else why not. Never quotes either token."""
        if not self._token:
            return "no agent token configured on the core (TRADINGOS_AGENT_TOKEN) — every agent is refused"
        if not presented:
            return "hello without a token — agent older than I1, or tradingos_agent.token missing from MQL5\\Files"
        if not hmac.compare_digest(presented.encode("utf-8"), self._token.encode("utf-8")):
            return "wrong agent token — rerun scripts/start.ps1 to rewrite tradingos_agent.token"
        return None

    async def _on_hello(self, hello: AgentHello, token: str | None, connection: _Connection) -> None:
        refusal = self._token_refusal(token)
        if refusal is not None:
            await self._safely(self._handler.on_refused(hello.agent_id, refusal))
            connection.close()
            return

        login = hello.account_id
        gave_up: str | None = None
        # A connection re-announcing itself under another login gives up its previous registration.
        previous = connection.login
        if previous is not None and previous != login and self._by_login.get(previous) is connection:
            del self._by_login[previous]
            gave_up = previous

        replaced: _Connection | None = None
        existing = self._by_login.get(login)
        if existing is not None and existing is not connection:
            if existing.silent_for(self._stale_after):
                replaced = existing  # a dead agent: the newcomer takes over at once
            else:
                await self._safely(self._handler.on_duplicate_refused(hello.agent_id))
                connection.close()
                if gave_up is not None:
                    await self._safely(self._handler.on_unregistered(gave_up))
                return

        self._by_login[login] = connection
        connection.login, connection.hello, connection.beat = login, hello, None  # a new hello starts a new status
        status = build_status(hello, None)
        connection.published = status
        if replaced is not None:
            replaced.close()  # its own cleanup finds it no longer registered: no removal, no event
        if gave_up is not None:
            await self._safely(self._handler.on_unregistered(gave_up))
        await self._safely(self._handler.on_registered(status))

    async def _safely(self, awaitable: object) -> None:
        try:
            await awaitable  # type: ignore[misc]
        except Exception:
            logger.exception("execution-agent handler failed")
