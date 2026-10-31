"""The sixteen readiness checks against a whole core: green when everything is, and — one fault at a time — red on exactly the
check that owns the fault, with a detail that says why. (The ladder's use of the verdict is tested with the autonomy service.)"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from tests.support.builders import make_command
from tests.support.core import AGENT_MAGIC, Core, make_core, make_ready_core
from tests.support.harness import Harness
from trading_os.domain.autonomy.readiness import ReadinessReport
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.execution.commands import CommandState
from trading_os.infrastructure.database.pool import Database

pytestmark = pytest.mark.db


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def verdict(core: Core) -> ReadinessReport:
    return await core.c.autonomy.readiness(fresh=True)


def detail(report: ReadinessReport, check: str) -> str:
    return next(c.detail for c in report.checks if c.check_id == check)


async def test_a_healthy_core_is_ready_with_all_sixteen_checks_green(h: Harness) -> None:
    core = await make_ready_core(h)
    report = await verdict(core)
    assert report.ready and report.blockers == [] and len(report.checks) == 16
    assert all(c.detail and c.ok for c in report.checks)


# ------------------------------------------------------------------------------------------------------ one fault, one check


async def break_database(core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    async def down() -> bool:
        return False

    monkeypatch.setattr(core.h.db, "ping", down)


async def switch_the_terminal_to_another_account(core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    from trading_os.infrastructure.mt5.fake import FakeAccount

    core.terminal.accounts[7_000_007] = FakeAccount(login=7_000_007, server="Exness-MT5Trial", password="x")
    core.terminal.current_login = 7_000_007


async def lose_the_quotes(core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    assert core.account is not None
    core.c.market.forget(core.account.id)


async def a_broken_specification(core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    real = core.c.market.spec

    def spec(account_id: str, symbol: str) -> object:
        found = real(account_id, symbol)
        return found.model_copy(update={"tick_value": 0.0, "tick_value_loss": None}) if found else None

    monkeypatch.setattr(core.c.market, "spec", spec)


async def a_failing_risk_engine(core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    core.c.risk.last_error = "database unavailable: today's trades are unknown"


async def an_agent_without_a_kill_switch(core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    status = core.link.statuses[core.login]
    core.link.statuses[core.login] = status.model_copy(update={"capabilities": ["ping"]})


async def a_supervisor_that_never_ran(core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    core.c.supervisor.last_tick_at = None


async def a_failing_execution_engine(core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    core.c.execution.last_error = "the command could not be recorded, so it was not sent"


async def a_critical_divergence(core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    assert core.account is not None
    core.terminal.add_position(identifier=999, symbol="EURUSDm", side=0, volume=0.05, price_open=1.1, sl=1.099,
                               magic=AGENT_MAGIC)  # fmt: skip
    await core.c.reconciliation.reconcile(core.account.id)


async def a_command_in_doubt(core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    assert core.account is not None
    await core.c.repos.execution.insert(
        make_command("cmd-doubt-1", account_id=core.account.id, state=CommandState.UNKNOWN), core.h.clock.now()
    )
    await core.c.reconciliation.reconcile(core.account.id)


FAULTS: list[tuple[str, Callable[[Core, pytest.MonkeyPatch], Awaitable[None]], set[str]]] = [
    ("database", break_database, {"database"}),
    ("another account", switch_the_terminal_to_another_account, {"correct_account"}),
    ("no quotes", lose_the_quotes, {"symbols_available", "sizing_valid"}),
    ("a specification that cannot size", a_broken_specification, {"sizing_valid"}),
    ("a failing risk engine", a_failing_risk_engine, {"risk_engine"}),
    ("an agent without a kill switch", an_agent_without_a_kill_switch, {"kill_switch_available"}),
    ("a supervisor that never ran", a_supervisor_that_never_ran, {"supervisor"}),
    ("a failing execution engine", a_failing_execution_engine, {"execution_engine"}),
    ("a critical divergence", a_critical_divergence, {"reconciliation"}),
    ("a command in doubt", a_command_in_doubt, {"reconciliation"}),
]


@pytest.mark.parametrize(("name", "fault", "blocked"), FAULTS, ids=[f[0] for f in FAULTS])
async def test_each_fault_turns_red_exactly_the_checks_that_own_it(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    fault: Callable[[Core, pytest.MonkeyPatch], Awaitable[None]],
    blocked: set[str],
) -> None:
    core = await make_ready_core(h)
    await fault(core, monkeypatch)
    report = await verdict(core)
    assert not report.ready and set(report.blockers) == blocked, report.blockers
    for check in blocked:
        assert detail(report, check) not in {"", "not evaluated"}


# ------------------------------------------------------------------------------------------------------ what time does to it


async def test_a_terminal_that_cannot_be_read_turns_the_terminal_and_the_account_checks_red(h: Harness) -> None:
    core = await make_ready_core(h)
    assert core.account is not None
    core.terminal.initialized = False
    await core.c.positions.poll(core.account.id)
    report = await verdict(core)
    assert set(report.blockers) == {"mt5_connected", "correct_account"}
    assert "failed read" in detail(report, "mt5_connected")


async def test_silence_makes_everything_that_depends_on_a_recent_beat_red_in_turn(h: Harness) -> None:
    core = await make_ready_core(h)
    h.clock.advance(seconds=11)  # past the core beat and the supervisor's allowance, not yet the others
    report = await verdict(core)
    assert set(report.blockers) == {"python_core", "supervisor"}
    h.clock.advance(seconds=6)  # past the terminal read and the agent heartbeat
    assert {"mt5_connected", "heartbeat"} <= set((await verdict(core)).blockers)
    h.clock.advance(seconds=10)  # past the risk cycle
    assert "risk_engine" in (await verdict(core)).blockers
    h.clock.advance(seconds=100)  # past the reconciliation
    assert "reconciliation" in (await verdict(core)).blockers
    await core.cycle()  # everything speaks again
    assert (await verdict(core)).ready


async def test_a_lost_agent_turns_the_kill_switch_and_the_heartbeat_red(h: Harness) -> None:
    core = await make_ready_core(h)
    core.link.statuses.clear()
    report = await verdict(core)
    assert set(report.blockers) == {"kill_switch_available", "heartbeat"}
    assert "no execution agent" in detail(report, "heartbeat")


# ------------------------------------------------------------------------------------------------------ red on purpose, for now


async def test_without_a_registered_strategy_and_exit_management_autonomy_stays_blocked_and_says_why(
    h: Harness,
) -> None:
    core = await make_core(h, providers=False)
    await core.add_account()
    await core.register_agent()
    for _ in range(2):
        h.clock.advance(seconds=2)
        await core.cycle()
    report = await verdict(core)
    assert set(report.blockers) == {"strategy_valid", "position_management"}
    assert "S01" in detail(report, "strategy_valid") and "TD-09" in detail(report, "position_management")


async def test_the_user_must_have_written_the_limits_and_fixed_the_reference_capital(h: Harness) -> None:
    core = await make_core(h)
    await core.add_account(configured=False)
    await core.register_agent()
    for _ in range(2):
        h.clock.advance(seconds=2)
        await core.cycle()
    report = await verdict(core)
    assert report.blockers == ["account_limits_configured"]
    assert "ADR 0015" in detail(report, "account_limits_configured")


async def test_a_critical_incident_blocks_autonomy_until_it_is_over(h: Harness) -> None:
    core = await make_ready_core(h)

    async def bug() -> None:
        raise RuntimeError("a defect")

    core.c.scheduler.add("bug-test", bug, interval_s=1.0, critical=True)
    for _ in range(5):
        await core.c.scheduler.run_once("bug-test")
    await core.c.supervisor.tick()
    report = await verdict(core)
    assert {"no_critical_incident", "supervisor"} <= set(report.blockers)
    assert "critical_error" in detail(report, "no_critical_incident")


async def test_with_no_active_account_nothing_but_the_core_and_the_database_can_be_green(h: Harness) -> None:
    core = await make_core(h)
    await core.c.heartbeat.beat()
    report = await verdict(core)
    assert set(report.blockers) == {c.check_id for c in report.checks} - {"python_core", "database"}
    assert all("no active account" in detail(report, c) for c in report.blockers)


async def test_arming_an_automatic_rung_names_what_is_wrong(h: Harness) -> None:
    from trading_os.shared.errors import Forbidden

    core = await make_ready_core(h, top=AutonomyMode.CONFIRM)
    core.link.statuses.clear()
    with pytest.raises(Forbidden) as caught:
        await core.c.autonomy.arm(AutonomyMode.ARMED)
    assert caught.value.code == "not_ready" and set(caught.value.details["blockers"]) == {
        "kill_switch_available",
        "heartbeat",
    }
