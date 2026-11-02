"""The engine: what starts, in which order, what runs on the clock, and how it stops — against the real container."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from pydantic import SecretStr

from tests.support.builders import make_command
from tests.support.core import Core, ScriptedLink, make_core, make_ready_core
from tests.support.harness import Harness
from tests.support.postgres import Server, unique_name
from trading_os.app.config import Settings
from trading_os.app.container import build_container
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.events import AutonomyDisarmed, ExecutionUnknown, SystemHeartbeat
from trading_os.domain.execution.commands import CommandState
from trading_os.infrastructure.database.pool import Database
from trading_os.runtime.engine import Engine

pytestmark = pytest.mark.db

FAST = {
    "heartbeat_interval_s": 0.05,
    "positions_poll_interval_s": 0.05,
    "tick_poll_interval_s": 0.05,
    "supervisor_interval_s": 0.05,
}
JOBS = {
    "heartbeat", "positions", "ticks", "candles", "risk", "strategy", "position_manager", "guardian", "execution",
    "reconciliation", "autonomy", "supervisor", "tick_writer", "news",
}  # fmt: skip


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def eventually(condition: Any, timeout: float = 5.0) -> None:
    """Wait for a CONDITION, never for a fixed time: the loop runs on the real clock and the machine may be busy."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the condition never became true")
        await asyncio.sleep(0.02)


# ------------------------------------------------------------------------------------------------------ starting


async def test_commands_left_in_flight_are_put_out_of_harms_way_before_anything_else(h: Harness) -> None:
    for command_id, state in (
        ("cmd-pending", CommandState.PENDING),
        ("cmd-sent", CommandState.SENT),
        ("cmd-acknowledged", CommandState.ACKNOWLEDGED),
        ("cmd-done", CommandState.EXECUTED),
    ):
        await h.repos.execution.insert(make_command(command_id, account_id="A", state=state), h.clock.now())
    core = await make_core(h)  # the engine prepared: recovery ran
    states = {
        command_id: (await core.c.repos.execution.get(command_id)).state  # type: ignore[union-attr]
        for command_id in ("cmd-pending", "cmd-sent", "cmd-acknowledged", "cmd-done")
    }
    assert states == {
        "cmd-pending": CommandState.EXPIRED,  # never sent: stale
        "cmd-sent": CommandState.UNKNOWN,  # may have reached the broker: never replayed, reconciliation decides
        "cmd-acknowledged": CommandState.UNKNOWN,
        "cmd-done": CommandState.EXECUTED,  # settled: left alone
    }
    assert {e.command_id for e in core.recorder.of(ExecutionUnknown)} == {"cmd-sent", "cmd-acknowledged"}


async def test_the_core_always_starts_off(h: Harness) -> None:
    core = await make_core(h)
    assert core.c.autonomy.mode is AutonomyMode.OFF and not core.c.autonomy.permits_entries()


async def test_start_registers_every_job_with_its_cadence_and_marks_the_critical_ones(h: Harness) -> None:
    core = await make_core(h, settings=FAST)
    await core.engine.start()
    try:
        stats = {s.name: s for s in core.c.scheduler.stats()}
        assert set(stats) == JOBS
        assert {name for name, s in stats.items() if s.critical} == {
            "positions",
            "risk",
            "execution",
            "reconciliation",
            "supervisor",
        }  # fmt: skip  (the strategy is not a safety function: it is watched through the readiness, not the supervisor)
        assert stats["heartbeat"].interval_s == 0.05 and stats["news"].interval_s == 6 * 3600
        assert all(s.timeout_s for name, s in stats.items() if name != "heartbeat")
    finally:
        await core.engine.stop()


async def test_the_jobs_run_on_the_clock_and_stop_when_the_engine_stops(h: Harness) -> None:
    core = await make_core(h, settings=FAST)
    account = await core.add_account()
    await core.register_agent()
    await core.engine.start()
    try:
        await eventually(lambda: len(core.recorder.of(SystemHeartbeat)) >= 3)
        await eventually(lambda: core.c.positions.snapshot(account.id) is not None)
        await eventually(lambda: core.c.supervisor.last_tick_at is not None)
        await eventually(lambda: core.c.market.tick(account.id, "EURUSDm") is not None)
        assert core.engine.running
        assert all(s.unexpected_streak == 0 for s in core.c.scheduler.stats()), [
            (s.name, s.last_error) for s in core.c.scheduler.stats() if s.last_error
        ]
    finally:
        await core.engine.stop()
    assert not core.engine.running
    beats = len(core.recorder.of(SystemHeartbeat))
    await asyncio.sleep(0.2)
    assert len(core.recorder.of(SystemHeartbeat)) == beats, "nothing runs after the stop"


async def test_one_job_failing_never_stops_the_others(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    core = await make_core(h, settings=FAST)
    await core.add_account(login=1_000_001)

    async def poll(account_id: str) -> bool:
        raise RuntimeError("a defect in the positions poll")

    def failures(job: str) -> int:
        stat = core.c.scheduler.stat(job)
        return stat.failures if stat is not None else 0

    def runs(job: str) -> int:
        stat = core.c.scheduler.stat(job)
        return stat.runs if stat is not None else 0

    monkeypatch.setattr(core.c.positions, "poll", poll)
    await core.engine.start()
    try:
        await eventually(lambda: failures("positions") > 0)
        stat = core.c.scheduler.stat("positions")
        assert stat is not None and "a defect" in (stat.last_error or "")
        # the other jobs kept running beside the broken one
        await eventually(lambda: runs("risk") > 0 and runs("heartbeat") > 0)
        assert failures("risk") == 0 and failures("heartbeat") == 0
    finally:
        await core.engine.stop()


# ------------------------------------------------------------------------------------------------------ stopping


async def test_a_graceful_stop_steps_an_armed_core_down_and_says_why(h: Harness) -> None:
    core = await make_ready_core(h, top=AutonomyMode.ARMED)
    await core.engine.start()
    await core.engine.stop()
    reasons = [e.reason for e in core.recorder.of(AutonomyDisarmed)]
    assert any("the core is shutting down" in reason for reason in reasons), reasons
    assert core.c.autonomy.mode is AutonomyMode.OBSERVE


async def test_an_account_that_disconnects_takes_its_caches_with_it(h: Harness) -> None:
    core = await make_ready_core(h, top=AutonomyMode.CONFIRM)
    assert core.account is not None
    account_id = core.account.id
    assert core.c.positions.snapshot(account_id) is not None and core.c.market.tick(account_id, "EURUSDm") is not None
    assert core.c.risk.status(account_id) is not None and core.c.reconciliation.report(account_id) is not None
    await core.c.accounts.disconnect(account_id)
    assert core.c.positions.snapshot(account_id) is None
    assert core.c.market.tick(account_id, "EURUSDm") is None and core.c.market.specs(account_id) == {}
    assert core.c.risk.status(account_id) is None and core.c.reconciliation.report(account_id) is None


# ------------------------------------------------------------------------------------------------------ the wiring that matters most


async def test_the_agent_socket_is_the_one_the_execution_service_listens_to(h: Harness) -> None:
    """No scripted link: the container builds the real TCP server and hands it the execution service as its handler. An
    agent that says hello on the socket (with the token) must appear in the execution service."""
    settings = Settings(_env_file=None, ea_link_port=0)
    settings.trading_os_agent_token = SecretStr("an-agent-token-for-tests")  # (the field is read by its alias only)
    container = build_container(settings, db=h.db, clock=h.clock, mt5_factory=h.mt5_factory)
    engine = Engine(container)
    await engine.prepare()
    try:
        assert container.ea_server is not None and container.ea_server.port > 0
        reader, writer = await asyncio.open_connection("127.0.0.1", container.ea_server.port)
        hello = {
            "version": 1, "type": "agent.hello", "accountId": "1000001", "time": 0, "agentId": "mt5-execution-agent-7001",
            "capabilities": ["ping", "halt"], "identity": "ok", "tradable": True, "token": "an-agent-token-for-tests",
        }  # fmt: skip
        writer.write((json.dumps(hello) + "\n").encode())
        await writer.drain()
        await eventually(lambda: container.execution.agent_status("1000001") is not None)
        status = container.execution.agent_status("1000001")
        assert status is not None and status.magic_number == 7001 and status.can("halt")

        # …and a wrong token is refused, never registered
        reader2, writer2 = await asyncio.open_connection("127.0.0.1", container.ea_server.port)
        writer2.write((json.dumps({**hello, "accountId": "2000002", "token": "wrong"}) + "\n").encode())
        await writer2.drain()
        await asyncio.sleep(0.2)
        assert container.execution.agent_status("2000002") is None
        writer.close()
        writer2.close()
        del reader, reader2
    finally:
        await engine.stop()


async def test_start_applies_pending_migrations_before_anything_else(pg_server: Server) -> None:
    name = unique_name()
    url = pg_server.create_database(name)  # a blank database: not one table
    try:
        db = Database(url, min_size=1, max_size=2)
        container = build_container(Settings(_env_file=None), db=db, agent_link=ScriptedLink())
        engine = Engine(container, migrate_url=url)
        await engine.prepare()
        try:
            applied = await db.fetch_all("SELECT version FROM schema_migrations ORDER BY version")
            assert [r["version"] for r in applied][:2] == ["0001", "0002"]
            assert await db.fetch_value("SELECT count(*) FROM accounts") == 0
        finally:
            await engine.stop()
    finally:
        pg_server.drop_database(name)


async def test_engine_is_idempotent_to_start_and_to_stop(h: Harness) -> None:
    core: Core = await make_core(h, settings=FAST)
    await core.engine.start()
    await core.engine.start()  # a second start changes nothing
    await core.engine.stop()
    await core.engine.stop()  # nor a second stop
    assert not core.engine.running
