"""The execution-agent link over **real loopback sockets** : registry, token,
duplicate refusal, dead-agent replacement, watchdog, ping, halt, framing and concurrency."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest

from trading_os.domain.execution.agent import AgentStatus
from trading_os.domain.primitives import Side
from trading_os.infrastructure.mt5.ea_link import EaLinkServer, NullHandler
from trading_os.infrastructure.mt5.wire import (
    AgentHeartbeat,
    ExecutionAck,
    ExecutionReconciled,
    ExecutionReport,
    PositionScan,
    order_line,
)

TOKEN = "agent-token-for-tests"
LOGIN = "1000001"  # fake login: tests never use a real account number


class Recorder(NullHandler):
    def __init__(self) -> None:
        self.registered: list[AgentStatus] = []
        self.unregistered: list[str] = []
        self.status_changes: list[AgentStatus] = []
        self.heartbeats: list[tuple[str, AgentHeartbeat]] = []
        self.acks: list[tuple[str, ExecutionAck]] = []
        self.reports: list[tuple[str, ExecutionReport]] = []
        self.reconciled: list[tuple[str, ExecutionReconciled]] = []
        self.scans: list[tuple[str, PositionScan]] = []
        self.refused: list[tuple[str, str]] = []
        self.duplicates: list[str] = []

    async def on_registered(self, status: AgentStatus) -> None:
        self.registered.append(status)

    async def on_unregistered(self, login: str) -> None:
        self.unregistered.append(login)

    async def on_status_changed(self, status: AgentStatus) -> None:
        self.status_changes.append(status)

    async def on_heartbeat(self, login: str, beat: AgentHeartbeat) -> None:
        self.heartbeats.append((login, beat))

    async def on_ack(self, login: str, ack: ExecutionAck) -> None:
        self.acks.append((login, ack))

    async def on_report(self, login: str, report: ExecutionReport) -> None:
        self.reports.append((login, report))

    async def on_reconciled(self, login: str, reconciled: ExecutionReconciled) -> None:
        self.reconciled.append((login, reconciled))

    async def on_position_scan(self, login: str, scan: PositionScan) -> None:
        self.scans.append((login, scan))

    async def on_refused(self, agent_id: str, reason: str) -> None:
        self.refused.append((agent_id, reason))

    async def on_duplicate_refused(self, agent_id: str) -> None:
        self.duplicates.append(agent_id)


class FakeAgent:
    """Plays the MQL5 agent: dials in, speaks NDJSON."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.reader: asyncio.StreamReader
        self.writer: asyncio.StreamWriter

    async def connect(self) -> FakeAgent:
        self.reader, self.writer = await asyncio.open_connection("127.0.0.1", self.port)
        return self

    async def send(self, payload: dict[str, Any] | str) -> None:
        line = payload if isinstance(payload, str) else json.dumps(payload)
        self.writer.write(line.encode("utf-8") + b"\n")
        await self.writer.drain()

    def hello_payload(self, login: str = LOGIN, token: str | None = TOKEN, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": 1,
            "type": "agent.hello",
            "accountId": login,
            "time": 1_700_000_000_000,
            "agentId": f"mt5-execution-agent-{login}",
            "symbol": "EURUSDm",
            "broker": "Test Broker",
            "server": "Test-Server",
            "orderTypes": ["market"],
            "minVolume": 0.01,
            "maxVolume": 200,
            "volumeStep": 0.01,
            "fillingMode": "IOC",
            "stopsLevelPoints": 0,
            "mode": "observe",
            "agentVersion": "1.10",
            "serverUtcOffsetMinutes": 0,
            "capabilities": ["ping", "halt"],
            "modeCeiling": "observe",
            "identity": "ok",
            "tradable": True,
            "halted": False,
            "terminalTradeAllowed": True,
            "expertTradeAllowed": True,
            "accountTradeExpert": True,
            "accountTradeAllowed": True,
            "attachedExperts": [],
        }
        if token is not None:
            payload["token"] = token
        payload.update(overrides)
        return payload

    async def hello(self, login: str = LOGIN, token: str | None = TOKEN, **overrides: Any) -> None:
        await self.send(self.hello_payload(login, token, **overrides))

    async def recv(self, timeout: float = 2.0) -> dict[str, Any]:
        raw = await asyncio.wait_for(self.reader.readline(), timeout)
        return json.loads(raw)  # type: ignore[no-any-return]

    async def closed_by_server(self, timeout: float = 2.0) -> bool:
        try:
            return await asyncio.wait_for(self.reader.read(1), timeout) == b""
        except (TimeoutError, ConnectionError):
            return False

    async def close(self) -> None:
        self.writer.close()
        with contextlib.suppress(Exception):
            await self.writer.wait_closed()


async def eventually(condition: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.01)


@pytest.fixture
async def make_server() -> AsyncIterator[Callable[..., Awaitable[tuple[EaLinkServer, Recorder]]]]:
    servers: list[EaLinkServer] = []
    agents: list[FakeAgent] = []

    async def factory(**kwargs: Any) -> tuple[EaLinkServer, Recorder]:
        recorder = Recorder()
        options: dict[str, Any] = {
            "host": "127.0.0.1",
            "port": 0,
            "token": TOKEN,
            "handler": recorder,
            "stale_after": 30.0,
            "ping_interval": 60.0,
        }
        options.update(kwargs)
        server = EaLinkServer(**options)
        await server.start()
        servers.append(server)
        return server, recorder

    yield factory
    for agent in agents:
        await agent.close()
    for server in servers:
        await server.stop()


async def agent_for(server: EaLinkServer) -> FakeAgent:
    return await FakeAgent(server.port).connect()


class TestRegistry:
    async def test_a_valid_hello_registers_the_agent(self, make_server: Any) -> None:
        server, rec = await make_server()
        agent = await agent_for(server)
        await agent.hello()
        await eventually(lambda: server.is_connected(LOGIN))
        assert rec.registered[0].agent_id == f"mt5-execution-agent-{LOGIN}" and rec.registered[0].identity == "ok"
        status = server.status(LOGIN)
        assert status is not None and status.healthy_for_orders and status.capabilities == ["ping", "halt"]
        assert server.registered_logins() == [LOGIN] and not server.is_connected("999")
        await agent.close()
        await eventually(lambda: not server.is_connected(LOGIN))
        assert rec.unregistered == [LOGIN]

    async def test_a_second_agent_for_a_live_login_is_refused_and_the_first_keeps_it(self, make_server: Any) -> None:
        server, rec = await make_server()
        first, second = await agent_for(server), await agent_for(server)
        await first.hello()
        await eventually(lambda: server.is_connected(LOGIN))
        await second.hello(agentId="the-intruder")
        await eventually(lambda: rec.duplicates == ["the-intruder"])
        assert await second.closed_by_server()
        assert server.is_connected(LOGIN) and len(rec.registered) == 1 and rec.unregistered == []

    async def test_a_dead_agent_is_replaced_at_once(self, make_server: Any) -> None:
        server, rec = await make_server(stale_after=0.3)
        first = await agent_for(server)
        await first.hello()
        await eventually(lambda: server.is_connected(LOGIN))
        await asyncio.sleep(0.45)  # silence past stale_after: the watchdog closes it, a newcomer takes the login
        second = await agent_for(server)
        await second.hello(agentId="the-replacement")
        await eventually(lambda: any(s.agent_id == "the-replacement" for s in rec.registered))
        assert server.is_connected(LOGIN) and rec.duplicates == []
        assert await first.closed_by_server()

    async def test_the_watchdog_closes_a_silent_agent(self, make_server: Any) -> None:
        server, rec = await make_server(stale_after=0.3)
        agent = await agent_for(server)
        await agent.hello()
        await eventually(lambda: server.is_connected(LOGIN))
        await eventually(lambda: not server.is_connected(LOGIN), timeout=2.0)
        assert rec.unregistered == [LOGIN] and await agent.closed_by_server()

    async def test_a_live_agent_is_not_closed_by_the_watchdog(self, make_server: Any) -> None:
        server, _ = await make_server(stale_after=0.4)
        agent = await agent_for(server)
        await agent.hello()
        for _ in range(8):
            await asyncio.sleep(0.1)
            await agent.send(
                {"version": 1, "type": "agent.heartbeat", "accountId": LOGIN, "time": 1, "agentId": "a", "latencyMs": 1}
            )
        assert server.is_connected(LOGIN)

    async def test_a_terminal_switching_account_gives_up_its_previous_registration(self, make_server: Any) -> None:
        server, rec = await make_server()
        agent = await agent_for(server)
        await agent.hello(login="1000001")
        await eventually(lambda: server.is_connected("1000001"))
        await agent.hello(login="1000002")
        await eventually(lambda: server.is_connected("1000002"))
        assert not server.is_connected("1000001") and rec.unregistered == ["1000001"]

    async def test_two_accounts_two_agents(self, make_server: Any) -> None:
        server, _ = await make_server()
        a, b = await agent_for(server), await agent_for(server)
        await a.hello(login="1000001")
        await b.hello(login="1000002")
        await eventually(lambda: server.registered_logins() == ["1000001", "1000002"])


class TestToken:
    async def test_no_token_configured_refuses_every_agent_fail_closed(self, make_server: Any) -> None:
        server, rec = await make_server(token=None)
        agent = await agent_for(server)
        await agent.hello()
        await eventually(lambda: len(rec.refused) == 1)
        assert "no agent token configured" in rec.refused[0][1] and not server.is_connected()
        assert await agent.closed_by_server()

    async def test_missing_and_wrong_tokens_are_refused_without_quoting_either(self, make_server: Any) -> None:
        server, rec = await make_server()
        for token in (None, "not-the-token"):
            agent = await agent_for(server)
            await agent.hello(token=token)
            assert await agent.closed_by_server()
        await eventually(lambda: len(rec.refused) == 2)
        assert not server.is_connected()
        for _, reason in rec.refused:
            assert TOKEN not in reason and "not-the-token" not in reason

    async def test_the_token_is_never_kept_in_the_status(self, make_server: Any) -> None:
        server, rec = await make_server()
        agent = await agent_for(server)
        await agent.hello()
        await eventually(lambda: server.is_connected(LOGIN))
        status = server.status(LOGIN)
        assert status is not None
        assert TOKEN not in status.model_dump_json() and TOKEN not in rec.registered[0].model_dump_json()


class TestFramingAndRouting:
    async def test_garbage_and_unknown_frames_are_dropped_the_link_survives(self, make_server: Any) -> None:
        server, rec = await make_server()
        agent = await agent_for(server)
        await agent.hello()
        await eventually(lambda: server.is_connected(LOGIN))
        for junk in (
            "not json at all",
            "[1,2,3]",
            '{"no":"type"}',
            '{"type":"mystery.type","accountId":"1"}',
            '{"type":"execution.ack"}',
        ):
            await agent.send(junk)
        await agent.send(
            {
                "version": 1,
                "type": "execution.ack",
                "accountId": LOGIN,
                "time": 1,
                "commandId": "cmd-1",
                "status": "ACCEPTED",
            }
        )
        await eventually(lambda: len(rec.acks) == 1)
        assert server.frames_dropped >= 5 and server.is_connected(LOGIN)

    async def test_a_byte_order_mark_at_the_start_of_the_stream_is_tolerated(self, make_server: Any) -> None:
        server, _ = await make_server()
        agent = await agent_for(server)
        agent.writer.write(b"\xef\xbb\xbf" + json.dumps(agent.hello_payload()).encode() + b"\n")
        await agent.writer.drain()
        await eventually(lambda: server.is_connected(LOGIN))

    async def test_nothing_counts_before_a_registered_hello(self, make_server: Any) -> None:
        server, rec = await make_server()
        agent = await agent_for(server)
        await agent.send(
            {
                "version": 1,
                "type": "execution.ack",
                "accountId": LOGIN,
                "time": 1,
                "commandId": "c",
                "status": "ACCEPTED",
            }
        )
        await agent.send(
            {
                "version": 1,
                "type": "execution.position.scan",
                "accountId": LOGIN,
                "time": 1,
                "brokerPositionId": "1",
                "symbol": "EURUSDm",
                "side": "BUY",
                "volume": 0.1,
            }
        )
        await asyncio.sleep(0.15)
        assert rec.acks == [] and rec.scans == [] and server.frames_dropped >= 2

    async def test_acks_reports_reconciliations_and_scans_are_routed_with_the_login(self, make_server: Any) -> None:
        server, rec = await make_server()
        agent = await agent_for(server)
        await agent.hello()
        await eventually(lambda: server.is_connected(LOGIN))
        await agent.send(
            {
                "version": 1,
                "type": "execution.ack",
                "accountId": LOGIN,
                "time": 1,
                "commandId": "cmd-1",
                "status": "REJECTED",
                "reason": "ACCOUNT_MISMATCH",
            }
        )
        await agent.send(
            {
                "version": 1,
                "type": "execution.report",
                "accountId": LOGIN,
                "time": 2,
                "commandId": "cmd-1",
                "status": "FILLED",
                "symbol": "EURUSDm",
                "side": "BUY",
                "brokerOrderId": 123456,
                "brokerPositionId": "123456",
                "filledVolume": 0.09,
                "averagePrice": 1.1,
                "brokerRetcode": 10009,
                "detail": "FILLED",
            }
        )
        await agent.send(
            {
                "version": 1,
                "type": "execution.reconciled",
                "accountId": LOGIN,
                "time": 3,
                "commandId": "cmd-2",
                "outcome": "not_found",
                "attempts": 2,
                "detail": "nothing in history",
            }
        )
        await agent.send(
            {
                "version": 1,
                "type": "execution.position.scan",
                "accountId": LOGIN,
                "time": 4,
                "brokerPositionId": 99,
                "symbol": "EURUSDm",
                "side": "SELL",
                "volume": 0.1,
                "magicNumber": 1001,
                "isExternal": False,
                "knownCommandId": "cmd-1",
            }
        )
        await eventually(lambda: rec.acks and rec.reports and rec.reconciled and rec.scans)
        assert (
            rec.acks[0][0] == LOGIN
            and rec.acks[0][1].status == "REJECTED"
            and rec.acks[0][1].reason == "ACCOUNT_MISMATCH"
        )
        report = rec.reports[0][1]
        # an older agent sent ids and return codes as JSON numbers: they are strings by the time the core sees them
        assert (report.broker_order_id, report.broker_position_id, report.broker_retcode) == (
            "123456",
            "123456",
            "10009",
        )
        assert rec.reconciled[0][1].outcome == "not_found" and rec.reconciled[0][1].attempts == 2
        scan = rec.scans[0][1]
        assert (scan.broker_position_id, scan.known_command_id, scan.magic_number) == ("99", "cmd-1", 1001)

    async def test_status_changes_are_published_but_clocks_alone_say_nothing(self, make_server: Any) -> None:
        server, rec = await make_server()
        agent = await agent_for(server)
        await agent.hello()
        await eventually(lambda: server.is_connected(LOGIN))
        beat = {
            "version": 1,
            "type": "agent.heartbeat",
            "accountId": LOGIN,
            "agentId": "a",
            "latencyMs": 1,
            "mode": "observe",
            "identity": "ok",
            "halted": False,
            "attachedExperts": [],
        }
        await agent.send({**beat, "time": 10, "coreSilentMs": 1000})
        await agent.send({**beat, "time": 20, "gatewaySilentMs": 6000})  # the name agents built before 1.11 still send
        await eventually(lambda: len(rec.heartbeats) == 2)
        assert rec.status_changes == []  # only the two clocks moved
        status = server.status(LOGIN)
        assert status is not None and status.core_silent_ms == 6000  # …and both spellings reach the same field
        await agent.send({**beat, "time": 30, "halted": True})
        await eventually(lambda: len(rec.status_changes) == 1)
        status = server.status(LOGIN)
        assert status is not None and status.halted is True and status.command_refusal() is not None
        assert not status.healthy_for_orders

    async def test_another_expert_attached_is_a_state_change(self, make_server: Any) -> None:
        server, rec = await make_server()
        agent = await agent_for(server)
        await agent.hello()
        await eventually(lambda: server.is_connected(LOGIN))
        await agent.send(
            {
                "version": 1,
                "type": "agent.heartbeat",
                "accountId": LOGIN,
                "time": 5,
                "agentId": "a",
                "latencyMs": 1,
                "attachedExperts": ["Some_Third_Party_EA"],
            }
        )
        await eventually(lambda: len(rec.status_changes) == 1)
        assert rec.status_changes[0].attached_experts == ["Some_Third_Party_EA"]


class TestSending:
    def an_order(self, command_id: str = "cmd-1") -> bytes:
        return order_line(
            login=LOGIN,
            command_id=command_id,
            expires_at_ms=2_000_000_000_000,
            now_ms=1_700_000_000_000,
            symbol="EURUSDm",
            side=Side.BUY,
            volume=0.09,
            stop_loss=1.099,
            take_profit=1.103,
        )

    async def test_an_order_reaches_the_agent_in_the_documented_shape(self, make_server: Any) -> None:
        server, _ = await make_server()
        agent = await agent_for(server)
        await agent.hello()
        await eventually(lambda: server.is_connected(LOGIN))
        assert await server.send_line(LOGIN, self.an_order())
        frame = await agent.recv()
        assert frame == {
            "version": 1,
            "type": "execution.order",
            "accountId": LOGIN,
            "time": 1_700_000_000_000,
            "id": "cmd-1",
            "expiresAt": 2_000_000_000_000,
            "symbol": "EURUSDm",
            "side": "BUY",
            "orderType": "MARKET",
            "volume": 0.09,
            "limitPrice": None,
            "sl": 1.099,
            "tp": 1.103,
        }

    async def test_the_order_line_has_no_byte_order_mark(self) -> None:
        assert not self.an_order().startswith(b"\xef\xbb\xbf") and self.an_order().endswith(b"\n")

    async def test_unreachable_when_no_agent_is_registered_never_a_silent_no_op(self, make_server: Any) -> None:
        server, _ = await make_server()
        assert await server.send_line(LOGIN, self.an_order()) is False
        assert await server.send_halt(LOGIN, "x") is False

    async def test_a_send_to_a_closed_agent_fails(self, make_server: Any) -> None:
        server, _ = await make_server()
        agent = await agent_for(server)
        await agent.hello()
        await eventually(lambda: server.is_connected(LOGIN))
        await agent.close()
        await eventually(lambda: not server.is_connected(LOGIN))
        assert await server.send_line(LOGIN, self.an_order()) is False

    async def test_halt_is_sent_only_to_agents_that_understand_it(self, make_server: Any) -> None:
        server, _ = await make_server()
        capable, legacy = await agent_for(server), await agent_for(server)
        await capable.hello(login="1000001")
        await legacy.hello(login="1000002", capabilities=[])
        await eventually(lambda: len(server.registered_logins()) == 2)
        assert await server.send_halt("1000001", "reconciliation failed") is True
        frame = await capable.recv()
        assert frame["type"] == "control.halt" and frame["reason"] == "reconciliation failed"
        assert await server.send_halt("1000002", "x") is False

    async def test_ping_goes_only_to_agents_that_announce_the_capability(self, make_server: Any) -> None:
        server, _ = await make_server(ping_interval=0.1)
        capable, legacy = await agent_for(server), await agent_for(server)
        await capable.hello(login="1000001", capabilities=["ping"])
        await legacy.hello(login="1000002", capabilities=[])
        await eventually(lambda: len(server.registered_logins()) == 2)
        frame = await capable.recv(timeout=1.0)
        assert frame["type"] == "control.ping" and isinstance(frame["time"], int)
        with pytest.raises(TimeoutError):
            await legacy.recv(timeout=0.35)

    async def test_concurrent_senders_never_interleave_lines(self, make_server: Any) -> None:
        server, _ = await make_server()
        agent = await agent_for(server)
        await agent.hello()
        await eventually(lambda: server.is_connected(LOGIN))
        big = "X" * 4000
        lines = [
            order_line(
                login=LOGIN,
                command_id=f"cmd-{i:03d}-{big}",
                expires_at_ms=1,
                now_ms=1,
                symbol="EURUSDm",
                side=Side.BUY,
                volume=0.01,
                stop_loss=1.0,
                take_profit=1.2,
            )
            for i in range(40)
        ]
        results = await asyncio.gather(*(server.send_line(LOGIN, line) for line in lines))
        assert all(results)
        received = [await agent.recv(timeout=3.0) for _ in lines]  # every line parses: none was torn
        assert {frame["id"][:7] for frame in received} == {f"cmd-{i:03d}" for i in range(40)}
