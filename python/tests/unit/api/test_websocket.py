"""The live stream: the per-client bounded queue (what is dropped, what never is, when a client is closed), the hub's protocol
(snapshot first, subscribe, resync) with a scripted socket, and the whole thing end to end on a real loopback socket."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.typing import Origin

from tests.support.api import ORIGIN, TOKEN, make_api, serving
from tests.support.harness import Harness
from trading_os.api.websocket.hub import Client, CockpitHub, Frame, is_droppable
from trading_os.domain.accounts.models import Environment
from trading_os.domain.events import (
    AccountConnected,
    CandleClosed,
    ExecutionAcknowledged,
    MarketTickReceived,
    PositionClosed,
    SystemHeartbeat,
)
from trading_os.domain.market.models import Candle, Tick
from trading_os.domain.positions.models import ClosedTrade
from trading_os.domain.primitives import Side, Timeframe
from trading_os.shared.time import ManualClock

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def lifecycle(n: int, account: str | None = None) -> Frame:
    return Frame(text=f"L{n}", account_id=account, droppable=False)


def telemetry(n: int, account: str | None = None) -> Frame:
    return Frame(text=f"T{n}", account_id=account, droppable=True)


class FakeSink:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed_with: int | None = None
        self.gate: asyncio.Event | None = None  # while set and not released, a send blocks: a slow client
        self.fail = False

    async def send_text(self, data: str) -> None:
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise ConnectionError("gone")
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


async def until(condition: Any, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the condition never became true")
        await asyncio.sleep(0.005)


# ------------------------------------------------------------------------------------------------------ the queue


async def test_a_client_is_sent_its_frames_in_order() -> None:
    sink = FakeSink()
    client = Client(sink)
    writer = asyncio.create_task(client.run())
    for n in range(5):
        client.offer(lifecycle(n))
    await until(lambda: len(sink.sent) == 5)
    assert sink.sent == [f"L{n}" for n in range(5)] and client.sent == 5 and client.dropped == 0
    writer.cancel()


async def test_under_pressure_the_oldest_telemetry_goes_first_and_a_lifecycle_event_is_kept() -> None:
    client = Client(FakeSink(), capacity=3)  # (no writer: the queue fills)
    for frame in (lifecycle(1), telemetry(1), lifecycle(2)):
        client.offer(frame)
    client.offer(telemetry(2))  # full: the oldest telemetry (T1) makes room
    client.offer(lifecycle(3))  # full again: the only telemetry left (T2) makes room
    assert [f.text for f in client._queue] == ["L1", "L2", "L3"] and client.dropped == 2 and not client.overflowed


async def test_telemetry_that_finds_a_queue_full_of_lifecycle_events_is_the_one_dropped() -> None:
    client = Client(FakeSink(), capacity=2)
    client.offer(lifecycle(1))
    client.offer(lifecycle(2))
    client.offer(telemetry(1))
    assert [f.text for f in client._queue] == ["L1", "L2"] and client.dropped == 1 and not client.overflowed


async def test_a_client_too_slow_for_its_lifecycle_events_is_closed_with_1013_never_given_a_hole() -> None:
    sink = FakeSink()
    sink.gate = asyncio.Event()  # the client does not read
    client = Client(sink, capacity=3)
    writer = asyncio.create_task(client.run())
    client.offer(lifecycle(0))
    await asyncio.sleep(0.02)  # the writer takes L0 and blocks on the send
    for n in range(1, 5):  # L1-L3 fill the queue, L4 cannot be queued
        client.offer(lifecycle(n))
    assert client.overflowed
    sink.gate.set()
    await asyncio.wait_for(writer, 2)
    assert sink.closed_with == 1013 and client.closed
    client.offer(lifecycle(9))  # nothing is accepted any more
    assert sink.sent == ["L0"] or sink.sent == []


async def test_a_socket_that_fails_ends_the_writer_quietly() -> None:
    sink = FakeSink()
    sink.fail = True
    client = Client(sink)
    writer = asyncio.create_task(client.run())
    client.offer(lifecycle(1))
    await asyncio.wait_for(writer, 2)
    assert client.closed and client.sent == 0


async def test_a_client_wants_its_accounts_and_every_global_event() -> None:
    client = Client(FakeSink())
    assert client.wants("A") and client.wants(None)
    client.accounts = frozenset({"A"})
    assert client.wants("A") and client.wants(None) and not client.wants("B")


async def test_a_snapshot_goes_ahead_of_what_was_queued_while_it_was_built() -> None:
    client = Client(FakeSink())
    client.offer(lifecycle(1))
    client.push_first(lifecycle(0))
    assert [f.text for f in client._queue] == ["L0", "L1"]


def test_only_telemetry_may_be_dropped_and_a_closed_candle_is_a_fact() -> None:
    tick = Tick(symbol="EURUSDm", bid=1.1, ask=1.1001, time=NOW)
    candle = Candle(symbol="EURUSDm", timeframe=Timeframe.M1, open_time=NOW, open=1, high=1, low=1, close=1)
    closed = ClosedTrade(account_id="A", broker_position_id="1", symbol="EURUSDm", side=Side.BUY, volume=0.1,
                         realized_pnl=1.0, exit_price=1.1, closed_at=NOW)  # fmt: skip
    assert is_droppable(MarketTickReceived(account_id="A", tick=tick)) and is_droppable(
        SystemHeartbeat(seq=1, uptime_seconds=1)
    )
    assert not is_droppable(CandleClosed(account_id="A", candle=candle))  # persist=False, yet not telemetry
    assert not is_droppable(PositionClosed(account_id="A", trade=closed))
    assert not is_droppable(ExecutionAcknowledged(account_id="A", command_id="c", status="ACCEPTED"))


# ------------------------------------------------------------------------------------------------------ the hub's protocol


class FakeSocket:
    """The server side of a WebSocket as the hub sees it, scripted by the test."""

    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[dict[str, Any]] = []
        self.closed_code: int | None = None
        self.incoming: asyncio.Queue[str | None] = asyncio.Queue()

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def receive_text(self) -> str:
        item = await self.incoming.get()
        if item is None:
            raise WebSocketDisconnect(1000)
        return item

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code


def make_hub() -> tuple[CockpitHub, list[frozenset[str] | None]]:
    scopes: list[frozenset[str] | None] = []

    async def snapshot(accounts: frozenset[str] | None) -> dict[str, Any]:
        scopes.append(accounts)
        return {"accounts": sorted(accounts) if accounts is not None else "all", "n": len(scopes)}

    return CockpitHub(snapshot, clock=ManualClock(NOW)), scopes


def connected(account: str, n: int = 1) -> AccountConnected:
    return AccountConnected(account_id=account, server="s", currency="USD", environment=Environment.DEMO)


async def test_the_first_frame_is_the_snapshot_then_events_follow() -> None:
    hub, _ = make_hub()
    socket = FakeSocket()
    served = asyncio.create_task(hub.serve(socket))  # type: ignore[arg-type]
    await until(lambda: len(socket.sent) == 1)
    first = socket.sent[0]
    assert socket.accepted and first["type"] == "system.snapshot" and first["accountId"] is None
    assert (
        first["payload"] == {"accounts": "all", "n": 1}
        and first["occurredAt"].endswith("Z")
        and first["id"].startswith("snap-")
    )

    await hub.on_event(connected("A"))
    await until(lambda: len(socket.sent) == 2)
    assert socket.sent[1]["type"] == "account.connected" and socket.sent[1]["accountId"] == "A"
    assert socket.sent[1]["payload"]["currency"] == "USD"
    socket.incoming.put_nowait(None)
    await asyncio.wait_for(served, 2)
    assert hub.stats().clients == 0 and hub.stats().frames_sent == 2


async def test_subscribing_narrows_the_events_and_the_snapshot_and_global_events_always_pass() -> None:
    hub, scopes = make_hub()
    socket = FakeSocket()
    served = asyncio.create_task(hub.serve(socket))  # type: ignore[arg-type]
    await until(lambda: len(socket.sent) == 1)
    socket.incoming.put_nowait(json.dumps({"type": "subscribe", "accountIds": ["A"]}))
    await until(lambda: len(socket.sent) == 2)
    assert scopes[-1] == frozenset({"A"}) and socket.sent[1]["payload"]["accounts"] == ["A"]

    await hub.on_event(connected("B"))  # another account: not for this client
    await hub.on_event(SystemHeartbeat(seq=1, uptime_seconds=1.0))  # global: always
    await hub.on_event(connected("A"))
    await until(lambda: len(socket.sent) == 4)
    assert [f["type"] for f in socket.sent[2:]] == ["system.heartbeat", "account.connected"]

    socket.incoming.put_nowait(json.dumps({"type": "subscribe"}))  # no list: every account again
    await until(lambda: len(socket.sent) == 5)
    assert scopes[-1] is None
    socket.incoming.put_nowait(None)
    await asyncio.wait_for(served, 2)


async def test_a_resync_sends_a_fresh_snapshot_and_garbage_is_ignored() -> None:
    hub, scopes = make_hub()
    socket = FakeSocket()
    served = asyncio.create_task(hub.serve(socket))  # type: ignore[arg-type]
    await until(lambda: len(socket.sent) == 1)
    for junk in ("not json", json.dumps([1, 2]), json.dumps({"type": "teleport"}), json.dumps({"no": "type"})):
        socket.incoming.put_nowait(junk)
    socket.incoming.put_nowait(json.dumps({"type": "resync"}))
    await until(lambda: len(socket.sent) == 2)
    assert [f["type"] for f in socket.sent] == ["system.snapshot", "system.snapshot"] and len(scopes) == 2
    socket.incoming.put_nowait(None)
    await asyncio.wait_for(served, 2)


async def test_an_event_is_serialised_once_for_all_clients_and_nothing_happens_without_clients() -> None:
    hub, _ = make_hub()
    await hub.on_event(connected("A"))  # nobody is listening: no work, no error
    first, second = FakeSocket(), FakeSocket()
    tasks = [asyncio.create_task(hub.serve(s)) for s in (first, second)]  # type: ignore[arg-type]
    await until(lambda: len(first.sent) == 1 and len(second.sent) == 1)
    await hub.on_event(connected("A"))
    await until(lambda: len(first.sent) == 2 and len(second.sent) == 2)
    assert first.sent[1] == second.sent[1] and hub.stats().clients == 2
    for socket in (first, second):
        socket.incoming.put_nowait(None)
    await asyncio.gather(*tasks)


async def test_a_failing_snapshot_closes_the_connection_with_1011() -> None:
    async def broken(accounts: frozenset[str] | None) -> dict[str, Any]:
        raise RuntimeError("a defect")

    hub = CockpitHub(broken, clock=ManualClock(NOW))
    socket = FakeSocket()
    await asyncio.wait_for(hub.serve(socket), 2)  # type: ignore[arg-type]
    assert socket.closed_code == 1011 and hub.stats().clients == 0


# ------------------------------------------------------------------------------------------------------ on a real socket


@pytest.mark.db
async def test_the_socket_end_to_end_guarded_snapshot_first_then_the_cores_events(h: Harness) -> None:
    api = await make_api(h)
    try:
        async with serving(api.app) as port:
            base = f"ws://127.0.0.1:{port}/ws"
            # refused before the handshake completes: a foreign page, a wrong token, no token
            for uri, origin in ((f"{base}?access_token={TOKEN}", Origin("https://evil.example")),
                                (f"{base}?access_token=wrong", Origin(ORIGIN)), (base, Origin(ORIGIN))):  # fmt: skip
                with pytest.raises(InvalidStatus) as refused:
                    async with connect(uri, origin=origin):
                        pass
                assert refused.value.response.status_code == 403, uri

            async with connect(f"{base}?access_token={TOKEN}", origin=Origin(ORIGIN)) as ws:
                first = json.loads(await asyncio.wait_for(ws.recv(), 5))
                assert first["type"] == "system.snapshot"
                payload = first["payload"]
                account = api.core.account
                assert account is not None and payload["activeAccountId"] == account.id
                state = payload["accountStates"][account.id]
                assert state["snapshot"]["balance"] == 10000 and state["agent"]["agentId"] == "mt5-execution-agent-7001"
                assert payload["autonomy"]["state"]["mode"] == "OBSERVE" and payload["health"]["status"] == "ok"
                assert (await api.get("/api/system/health")).json()["websocket"]["clients"] == 1

                await api.core.c.events.publish(connected(account.id))  # something happens in the core …
                frame = json.loads(await asyncio.wait_for(ws.recv(), 5))  # … the cockpit hears about it
                assert frame["type"] == "account.connected" and frame["accountId"] == account.id

                await ws.send(json.dumps({"type": "subscribe", "accountIds": ["nobody"]}))
                narrowed = json.loads(await asyncio.wait_for(ws.recv(), 5))
                assert narrowed["type"] == "system.snapshot" and narrowed["payload"]["accountStates"] == {}
            await until(lambda: api.app.state.hub.stats().clients == 0)
            health = (await api.get("/api/system/health")).json()["websocket"]
            assert health["clients"] == 0 and health["framesSent"] >= 3
    finally:
        await api.close()


@pytest.mark.db
async def test_a_closed_socket_is_noticed_and_forgotten(h: Harness) -> None:
    api = await make_api(h)
    try:
        async with serving(api.app) as port:
            ws = await connect(f"ws://127.0.0.1:{port}/ws?access_token={TOKEN}", origin=Origin(ORIGIN))
            await asyncio.wait_for(ws.recv(), 5)
            await ws.close()
            with pytest.raises(ConnectionClosed):
                await ws.recv()
            await until(lambda: api.app.state.hub.stats().clients == 0)
    finally:
        await api.close()
