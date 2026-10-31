"""The supervisor against a whole core (real container, real database, simulated terminal, scripted agent): what each fault
looks like, what is done about it, and — as important — what is *not* done. Every scenario drives the cycles by hand; the
clock is the test's."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest

from tests.support.builders import make_command, make_intent
from tests.support.core import AGENT_MAGIC, Core, make_core, make_ready_core
from tests.support.harness import Harness
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.events import (
    AccountConnected,
    AutonomyDisarmed,
    AutonomyHalted,
    HeartbeatMissed,
    IncidentOpened,
    IncidentResolved,
    SystemHealthChanged,
)
from trading_os.domain.execution.commands import CommandState
from trading_os.domain.system.supervision import Severity
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.mt5.client import ConnectFailed
from trading_os.shared.errors import Unavailable

pytestmark = pytest.mark.db

M = AutonomyMode


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


def codes(core: Core) -> set[str]:
    return {f.code for f in core.c.supervisor.findings}


async def step(core: Core, seconds: float = 2.0, *, agent_beats: bool = True) -> None:
    core.h.clock.advance(seconds=seconds)
    await core.cycle(agent_beats=agent_beats)


def count_calls(
    monkeypatch: pytest.MonkeyPatch, target: object, name: str, clock: Callable[[], datetime]
) -> list[datetime]:
    """Wrap an async method so every call is recorded (with the test clock's time) and then goes through."""
    original: Callable[..., Awaitable[Any]] = getattr(target, name)
    calls: list[datetime] = []

    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        calls.append(clock())
        return await original(*args, **kwargs)

    monkeypatch.setattr(target, name, wrapper)
    return calls


# ------------------------------------------------------------------------------------------------------ the quiet case


async def test_a_healthy_core_has_no_findings_and_says_so_once(h: Harness) -> None:
    core = await make_ready_core(h)
    for _ in range(3):
        await step(core)
    supervisor = core.c.supervisor
    assert supervisor.findings == [] and supervisor.status() is Severity.OK
    assert supervisor.degraded_for(core.account.id if core.account else "") == []
    assert supervisor.open_incidents() == []
    assert len(core.recorder.of(SystemHealthChanged)) == 1  # one announcement of « all clear », not one per tick


# ------------------------------------------------------------------------------------------------------ database


async def test_a_database_that_does_not_answer_blocks_entries_and_halts_an_autonomous_core(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = await make_ready_core(h, top=M.AUTONOMOUS)
    assert core.account is not None
    answering = {"up": False}

    async def ping() -> bool:
        return answering["up"]

    monkeypatch.setattr(h.db, "ping", ping)
    await step(core)
    assert "database_unavailable" in codes(core)
    assert any("database_unavailable" in reason for reason in core.c.supervisor.degraded_for(core.account.id))
    assert core.c.autonomy.halted() and core.link.halts, "an autonomous core cannot persist anything: it halts"
    assert [i.severity for i in core.c.supervisor.open_incidents()] == [Severity.HIGH]

    for _ in range(3):  # the fault lasting is not a new incident, nor a new halt
        await step(core)
    assert len(core.recorder.of(IncidentOpened)) == 1 and len(core.link.halts) == 1

    answering["up"] = True
    await step(core)
    assert "database_unavailable" not in codes(core) and core.c.supervisor.degraded_for(core.account.id) == []
    assert core.recorder.of(IncidentResolved) and core.c.supervisor.open_incidents() == []
    assert core.c.autonomy.halted(), "a halt is lifted by a human, never by the fault clearing"


async def test_a_database_outage_only_blocks_entries_when_nothing_is_automatic(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = await make_ready_core(h, top=M.CONFIRM)

    async def ping() -> bool:
        return False

    monkeypatch.setattr(h.db, "ping", ping)
    await step(core)
    assert "database_unavailable" in codes(core) and not core.c.autonomy.halted() and core.link.halts == []


# ------------------------------------------------------------------------------------------------------ the terminal


async def test_a_dead_terminal_is_reattached_and_entries_are_blocked_meanwhile(h: Harness) -> None:
    core = await make_ready_core(h, top=M.CONFIRM)
    assert core.account is not None
    core.terminal.initialized = False  # the terminal crashed: every read fails
    await step(core)
    assert "mt5_disconnected" not in codes(core), "one failed read is not yet a fault"
    await step(core)
    assert "mt5_disconnected" in codes(core)
    assert core.c.supervisor.degraded_for(core.account.id), "entries are blocked while the terminal is down"
    assert len(core.recorder.of(AccountConnected)) == 2, "…and the supervisor re-attached it at once"

    await step(core)
    assert codes(core) == set() and core.c.supervisor.degraded_for(core.account.id) == []
    assert core.c.accounts.is_connected(core.account.id)


async def test_a_terminal_that_stays_dead_is_retried_with_a_back_off_then_an_armed_core_is_disarmed(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = await make_ready_core(h, top=M.ARMED)
    assert core.account is not None
    account_id = core.account.id
    attempts = count_calls(monkeypatch, core.c.accounts, "reconnect", h.clock.now)
    attempts_connect = count_calls(monkeypatch, core.c.accounts, "connect", h.clock.now)
    core.terminal.initialized = False
    core.terminal.initialize_fails = True  # it will not come back

    started = h.clock.now()
    # One-second ticks, 100 of them (attempts at ~2, 7, 17, 37 and 77 s); the autonomy duty is left out so that the
    # supervisor's own escalation is what shows.
    for _ in range(100):
        h.clock.advance(seconds=1)
        if core.c.accounts.is_connected(account_id):
            await core.c.positions.poll(account_id)
        await core.c.supervisor.tick()

    times = sorted({*attempts, *attempts_connect})  # `reconnect` calls `connect` inside: one attempt, one instant
    gaps = [(b - a).total_seconds() for a, b in pairwise(times)]
    assert gaps[:4] == [5.0, 10.0, 20.0, 40.0], gaps  # doubling, capped at a minute
    assert (times[0] - started).total_seconds() <= 3
    assert core.c.autonomy.mode is M.OBSERVE, "a fault outliving a minute disarms the automatic modes"
    assert "mt5_disconnected" in core.c.autonomy.state.last_transition.reason  # type: ignore[union-attr]
    assert not core.c.autonomy.halted(), "a lost terminal disarms, it does not halt"


async def test_an_account_that_dropped_is_retried_but_one_the_user_closed_is_not(h: Harness) -> None:
    core = await make_ready_core(h, top=M.CONFIRM)
    assert core.account is not None
    await core.c.accounts.mark_lost(core.account.id, "the link broke")
    await core.c.supervisor.tick()
    assert core.c.accounts.is_connected(core.account.id), "the supervisor re-attached the account the user wanted"

    await core.c.accounts.disconnect(core.account.id)  # the user's own gesture
    for _ in range(3):
        h.clock.advance(seconds=2)
        await core.c.supervisor.tick()
    assert "mt5_disconnected" not in codes(core) and not core.c.accounts.is_connected(core.account.id)


# ------------------------------------------------------------------------------------------------------ the execution agent


async def test_a_silent_agent_blocks_entries_and_disarms_an_armed_core_and_is_reported_once(h: Harness) -> None:
    core = await make_ready_core(h, top=M.ARMED)
    assert core.account is not None
    await step(core, 20, agent_beats=False)
    assert "agent_heartbeat_stale" in codes(core)
    assert core.c.autonomy.mode is M.OBSERVE, "an armed core with a mute agent is disarmed"
    assert core.c.supervisor.degraded_for(core.account.id)
    for _ in range(2):
        await step(core, 5, agent_beats=False)
    missed = core.recorder.of(HeartbeatMissed)
    assert len(missed) == 1 and missed[0].component == "execution-agent" and (missed[0].age_seconds or 0) >= 15

    await step(core)  # the agent speaks again
    assert "agent_heartbeat_stale" not in codes(core) and core.c.supervisor.degraded_for(core.account.id) == []
    assert core.c.autonomy.mode is M.OBSERVE, "…but a human climbs again"


async def test_an_agent_is_only_expected_where_orders_go_through_it(h: Harness) -> None:
    core = await make_ready_core(h, top=M.OBSERVE)
    core.link.statuses.clear()  # no agent at all: fine in OBSERVE
    await step(core, 40, agent_beats=False)  # (and long enough for the connection to be past its start-up grace)
    assert "agent_heartbeat_stale" not in codes(core)
    await core.c.autonomy.arm(M.PAPER)
    await step(core, agent_beats=False)
    assert "agent_heartbeat_stale" not in codes(core), "PAPER fills in process"
    await core.c.autonomy.arm(M.CONFIRM)
    await step(core, agent_beats=False)
    assert "agent_heartbeat_stale" in codes(core), "CONFIRM sends through the agent: its absence is a fault"


async def test_a_halt_reaches_an_agent_that_connects_after_it(h: Harness) -> None:
    core = await make_ready_core(h, top=M.CONFIRM)
    await core.c.autonomy.halt("test", actor="user")
    assert len(core.link.halts) == 1
    status = core.link.statuses[core.login]
    core.link.statuses[core.login] = status.model_copy(update={"halted": False})  # a fresh agent: not halted
    await core.c.supervisor.tick()
    assert len(core.link.halts) == 2 and core.link.statuses[core.login].halted is True


# ------------------------------------------------------------------------------------------------------ reconciliation


async def test_a_position_nobody_commanded_halts_everything_once(h: Harness) -> None:
    core = await make_ready_core(h, top=M.AUTONOMOUS)
    assert core.account is not None
    core.terminal.add_position(identifier=999, symbol="EURUSDm", side=0, volume=0.05, price_open=1.1, sl=1.099,
                               magic=AGENT_MAGIC)  # fmt: skip
    await step(core)
    assert "unexpected_position" in codes(core)
    assert core.c.autonomy.halted() and len(core.link.halts) == 1
    assert [i.severity for i in core.c.supervisor.open_incidents()] == [Severity.CRITICAL]
    assert core.recorder.of(AutonomyHalted)

    for _ in range(3):
        await step(core)
    assert len(core.link.halts) == 1, "the halt is not repeated at every tick"

    await core.c.autonomy.disarm(acknowledge=True)  # the human has looked
    assert core.c.autonomy.mode is M.OFF
    assert core.c.supervisor.open_incidents(), "the incident stays open while the position is there"
    core.terminal.remove_position(999)
    await step(core)
    await step(core)
    assert "unexpected_position" not in codes(core) and core.c.supervisor.open_incidents() == []
    assert core.recorder.of(IncidentResolved)


async def test_a_divergence_is_not_cleared_by_a_run_that_could_not_read(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = await make_ready_core(h, top=M.CONFIRM)
    core.terminal.add_position(identifier=997, symbol="EURUSDm", side=0, volume=0.05, price_open=1.1, sl=1.099,
                               magic=AGENT_MAGIC)  # fmt: skip
    await step(core)
    assert "unexpected_position" in codes(core) and core.c.autonomy.halted()

    async def unreadable(*args: object, **kwargs: object) -> list[object]:
        raise Unavailable("database unavailable", code="database_unavailable")

    monkeypatch.setattr(core.c.repos.execution, "created_since", unreadable)  # the next runs cannot read
    for _ in range(3):
        await step(core)
    assert "unexpected_position" in codes(core), "what could not be re-checked has not gone away"
    assert [i.code for i in core.c.supervisor.open_incidents() if i.code == "unexpected_position"] == [
        "unexpected_position"
    ]
    assert core.recorder.of(IncidentResolved) == []


async def test_a_position_opened_by_hand_is_not_an_emergency(h: Harness) -> None:
    core = await make_ready_core(h, top=M.AUTONOMOUS)
    core.terminal.add_position(identifier=998, symbol="EURUSDm", side=1, volume=0.02, price_open=1.1, magic=0)
    await step(core)
    assert core.c.supervisor.findings == [] and not core.c.autonomy.halted()


async def test_a_command_in_doubt_blocks_entries_and_forces_a_reconciliation_no_more_than_every_ten_seconds(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = await make_ready_core(h, top=M.CONFIRM)
    assert core.account is not None
    command = make_command("cmd-doubt-1", account_id=core.account.id, state=CommandState.UNKNOWN)
    await core.c.repos.execution.insert(command, h.clock.now())
    h.clock.advance(seconds=60)  # created long ago (the builders' clock starts at the harness epoch)
    calls = count_calls(monkeypatch, core.c.reconciliation, "reconcile", h.clock.now)
    await core.c.supervisor.tick()
    assert "unknown_command" in codes(core) and core.c.supervisor.degraded_for(core.account.id)
    assert len(calls) == 1
    h.clock.advance(seconds=2)
    await core.c.supervisor.tick()
    assert len(calls) == 1, "throttled"
    h.clock.advance(seconds=10)
    await core.c.supervisor.tick()
    assert len(calls) == 2
    assert not core.c.autonomy.halted(), "an unknown order is surfaced and reconciled, not a reason to halt"


async def test_a_reconciliation_that_keeps_failing_halts_once_the_fault_persists(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = await make_ready_core(h, top=M.CONFIRM)
    assert core.account is not None

    async def unreadable(*args: object, **kwargs: object) -> list[object]:
        raise Unavailable("database unavailable", code="database_unavailable")

    monkeypatch.setattr(core.c.repos.execution, "created_since", unreadable)  # only the reconciliation's own read fails
    for _ in range(3):
        await step(core)
    assert "reconciliation_failed" in codes(core)
    assert core.c.supervisor.degraded_for(core.account.id) == [], "its remedy is to reconcile, not to block entries"
    assert not core.c.autonomy.halted()
    for _ in range(35):
        await step(core)  # 70 s: the fault has outlived its first remedy
    assert core.c.autonomy.halted(), "a failure that persists is no longer a hiccup"


# ------------------------------------------------------------------------------------------------------ the core itself


async def test_a_critical_job_that_keeps_crashing_is_a_critical_error(h: Harness) -> None:
    core = await make_ready_core(h, top=M.CONFIRM)

    async def bug() -> None:
        raise RuntimeError("a defect")

    core.c.scheduler.add("risk-test", bug, interval_s=1.0, critical=True)
    for _ in range(4):
        await core.c.scheduler.run_once("risk-test")
    await core.c.supervisor.tick()
    assert "critical_error" not in codes(core), "four failures are a streak, not yet a verdict"
    await core.c.scheduler.run_once("risk-test")
    await core.c.supervisor.tick()
    assert "critical_error" in codes(core) and core.c.autonomy.halted()


async def test_a_job_that_stopped_finishing_is_a_stalled_core(h: Harness) -> None:
    core = await make_ready_core(h, top=M.CONFIRM)
    assert core.account is not None

    async def quick() -> None:
        return None

    core.c.scheduler.add("poll-test", quick, interval_s=2.0)
    await core.c.scheduler.run_once("poll-test")
    h.clock.advance(seconds=30)  # never run again
    await core.c.supervisor.tick()
    assert "scheduler_stalled" in codes(core) and core.c.supervisor.degraded_for(core.account.id)


# ------------------------------------------------------------------------------------------------------ incidents


async def test_incidents_open_once_resolve_when_the_fault_clears_and_survive_a_restart(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = await make_ready_core(h, top=M.CONFIRM)
    answering = {"up": False}

    async def ping() -> bool:
        return answering["up"]

    monkeypatch.setattr(h.db, "ping", ping)
    await step(core)
    opened = core.recorder.of(IncidentOpened)
    assert len(opened) == 1 and opened[0].incident.code == "database_unavailable"
    stored = await core.c.repos.incidents.open_incidents()
    assert [i.code for i in stored] == ["database_unavailable"]

    # the core restarts while the fault is still there: the incident is picked up, not duplicated
    second = await make_core(h)
    assert [i.code for i in second.c.supervisor.open_incidents()] == ["database_unavailable"]
    answering["up"] = True
    await second.c.supervisor.tick()
    assert second.recorder.of(IncidentResolved) and second.c.supervisor.open_incidents() == []
    assert await second.c.repos.incidents.open_incidents() == []


# ------------------------------------------------------------------------------------------------------ the Risk Engine reads SAFE


async def test_while_the_supervisor_is_in_safe_mode_every_decision_says_so(h: Harness) -> None:
    core = await make_ready_core(h, top=M.CONFIRM)
    assert core.account is not None
    intent = make_intent(core.account.id)
    healthy = await core.c.risk.review(intent)
    assert "system_degraded" not in healthy.reasons

    await step(core, 20, agent_beats=False)  # the agent goes silent: SAFE
    assert core.c.supervisor.degraded_for(core.account.id)
    blocked = await core.c.risk.review(make_intent(core.account.id))
    assert not blocked.approved and "system_degraded" in blocked.reasons

    await step(core)  # it speaks again: entries are possible again
    again = await core.c.risk.review(make_intent(core.account.id))
    assert "system_degraded" not in again.reasons


async def test_the_health_is_announced_when_it_changes_not_at_every_tick(h: Harness) -> None:
    core = await make_ready_core(h, top=M.CONFIRM)
    before = len(core.recorder.of(SystemHealthChanged))
    await step(core, 20, agent_beats=False)
    changed = core.recorder.of(SystemHealthChanged)
    assert len(changed) == before + 1 and changed[-1].status is Severity.HIGH
    assert {f.code for f in changed[-1].findings} == {"agent_heartbeat_stale"}
    await step(core, 2, agent_beats=False)
    assert len(core.recorder.of(SystemHealthChanged)) == before + 1  # same fault: nothing new to say
    await step(core)
    assert core.recorder.of(SystemHealthChanged)[-1].status is Severity.OK


async def test_a_graceful_disarm_is_recorded_with_the_supervisors_name(h: Harness) -> None:
    core = await make_ready_core(h, top=M.ARMED)
    await step(core, 20, agent_beats=False)
    reasons = [e.reason for e in core.recorder.of(AutonomyDisarmed)]
    assert any("supervisor" in reason and "agent_heartbeat_stale" in reason for reason in reasons), reasons


async def test_a_failing_reconnection_is_logged_and_never_raises_through_the_tick(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = await make_ready_core(h, top=M.CONFIRM)

    async def refuse(*args: object, **kwargs: object) -> None:
        raise ConnectFailed("the terminal cannot be started", code="terminal_unavailable")

    monkeypatch.setattr(core.c.accounts, "reconnect", refuse)
    core.terminal.initialized = False
    for _ in range(3):
        await step(core)  # must not raise
    assert "mt5_disconnected" in codes(core)
    assert timedelta(0) < timedelta(seconds=1)
