"""« Démarrer le système » (ADR 0034) against a whole core: the thirteen stages and what each says, the climb from OFF that never goes
past CONFIRM, the conditions before a position, and the separate gesture that authorises automatic trading.

Nothing here sends an order: the execution agent is a scripted double and the broker a simulated terminal."""

from __future__ import annotations

import pytest

from tests.support.core import Core, make_core
from tests.support.harness import Harness
from trading_os.domain.accounts.models import Environment
from trading_os.domain.autonomy.plan_modes import PlanMode
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.system.startup import (
    REAL_ACCOUNT_BANNER,
    StartupRunState,
    StartupStage,
    StartupStageState,
    StartupStatus,
)
from trading_os.infrastructure.database.pool import Database
from trading_os.services.startup import STAGE_LABELS, Timings
from trading_os.shared.errors import Forbidden, TradingOsError, ValidationFailed

pytestmark = pytest.mark.db

CAPS = ("ping", "halt", "close", "cancel", "modify", "limit", "dead_man")


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def make(
    h: Harness,
    *,
    agent: bool = True,
    environment: Environment = Environment.DEMO,
    max_mode: AutonomyMode = AutonomyMode.AUTONOMOUS,
) -> Core:
    core = await make_core(h)
    await core.add_account(environment=environment, max_mode=max_mode)
    if agent:
        await core.register_agent(capabilities=CAPS)
    for _ in range(2):
        h.clock.advance(seconds=2)
        await core.cycle(agent_beats=agent)
    core.c.startup._timings = Timings(agent_wait_s=0, market_wait_s=0, step_s=0)  # no real waiting in a test
    return core


async def start(core: Core, target: AutonomyMode = AutonomyMode.OBSERVE, **options: bool) -> StartupStatus:
    await core.c.startup.begin(target, **options)
    await core.c.startup.join()
    core.h.clock.advance(
        seconds=3
    )  # the readiness the screen reads is at most a couple of seconds old: let it be re-read
    return await core.c.startup.status()


def stage(status: StartupStatus, stage_id: str) -> StartupStage:
    return next(s for s in status.stages if s.stage_id == stage_id)


def check(status: StartupStatus, check_id: str):  # type: ignore[no-untyped-def]
    return next(c for c in status.checks if c.check_id == check_id)


# ------------------------------------------------------------------------------------------------------ before anything


async def test_before_starting_the_thirteen_stages_are_listed_and_the_system_is_off(h: Harness) -> None:
    core = await make(h)
    status = await core.c.startup.status()
    assert [s.stage_id for s in status.stages] == list(STAGE_LABELS) and len(status.stages) == 13
    assert [s.order for s in status.stages] == list(range(1, 14))
    assert status.mode is AutonomyMode.OFF and status.plan_mode is PlanMode.OFF and status.can_start
    assert stage(status, "application").state is StartupStageState.RUNNING
    assert stage(status, "database").state is StartupStageState.RUNNING
    assert (
        stage(status, "autonomy").state is StartupStageState.STOPPED
        and stage(status, "trading").state is StartupStageState.STOPPED
    )
    assert stage(status, "strategy").state is StartupStageState.STOPPED  # OFF: the strategies do not evaluate
    assert not status.entries_authorized and not status.can_authorize_automatic
    assert len(status.checks) == 22 and {c.source for c in status.checks} == {"readiness", "startup"}


async def test_without_any_account_the_status_says_so_and_nothing_is_green(h: Harness) -> None:
    core = await make_core(h)
    status = await core.c.startup.status()
    assert stage(status, "account").state is StartupStageState.FAILED and status.account is None
    assert "account" in status.blockers and not status.entries_authorized
    await core.c.startup.begin()
    await core.c.startup.join()
    run = (await core.c.startup.status()).run
    assert run is not None and run.state is StartupRunState.BLOCKED and run.blocked_on == ["account"]
    assert core.c.autonomy.mode is AutonomyMode.OFF


# ------------------------------------------------------------------------------------------------------ starting


async def test_starting_verifies_reconciles_and_climbs_to_observe_and_no_further(h: Harness) -> None:
    core = await make(h)
    assert core.account is not None
    before = core.c.reconciliation.last_success_at(core.account.id)
    h.clock.advance(seconds=1)
    status = await start(core)

    assert (
        status.run is not None
        and status.run.state is StartupRunState.DONE
        and status.run.reached_mode is AutonomyMode.OBSERVE
    )
    assert core.c.autonomy.mode is AutonomyMode.OBSERVE and status.plan_mode is PlanMode.OBSERVE
    after = core.c.reconciliation.last_success_at(core.account.id)
    assert after is not None and (before is None or after > before)  # forced on purpose, not left to the 15-second job
    assert (
        stage(status, "autonomy").state is StartupStageState.RUNNING
        and stage(status, "trading").state is StartupStageState.READY
    )
    assert not status.entries_authorized and "analysis only" in status.entries_reason
    assert core.link.lines == []  # starting sends nothing, ever
    assert not status.can_authorize_automatic and status.next_automatic_mode is None  # OBSERVE is not CONFIRM


async def test_a_second_press_while_running_returns_the_same_run(h: Harness) -> None:
    core = await make(h)
    first = await core.c.startup.begin()
    second = await core.c.startup.begin()
    assert first.run_id == second.run_id
    await core.c.startup.join()


async def test_starting_never_climbs_to_an_automatic_mode(h: Harness) -> None:
    core = await make(h)
    for target in (AutonomyMode.ARMED, AutonomyMode.AUTONOMOUS, AutonomyMode.HALTED, AutonomyMode.OFF):
        with pytest.raises(ValidationFailed) as refused:
            await core.c.startup.begin(target)
        assert refused.value.code == "invalid_target"
    assert core.c.autonomy.mode is AutonomyMode.OFF


async def test_starting_up_to_confirm_walks_the_ladder_when_every_condition_holds(h: Harness) -> None:
    core = await make(h)
    status = await start(core, AutonomyMode.CONFIRM)
    assert status.run is not None and status.run.state is StartupRunState.DONE, status.run
    assert (
        core.c.autonomy.mode is AutonomyMode.CONFIRM and status.plan_mode is PlanMode.CONFIRM
    )  # a demo: not LIVE_CONFIRM
    assert status.checks_green and status.entries_authorized and status.blockers == []
    assert stage(status, "trading").state is StartupStageState.RUNNING
    assert status.next_automatic_mode is AutonomyMode.ARMED and status.can_authorize_automatic
    assert core.link.lines == []


async def test_a_restart_never_resumes_automatic_trading(h: Harness) -> None:
    core = await make(h)
    await core.climb(AutonomyMode.ARMED)
    assert core.c.autonomy.mode is AutonomyMode.ARMED
    await core.c.autonomy.start()  # what the engine does when the core starts again
    assert core.c.autonomy.mode is AutonomyMode.OFF
    status = await core.c.startup.status()
    assert status.plan_mode is PlanMode.OFF and not status.entries_authorized and not status.can_authorize_automatic


# ------------------------------------------------------------------------------------------------------ what blocks


async def test_a_database_that_does_not_answer_blocks_the_start(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    core = await make(h)

    async def down() -> bool:
        return False

    monkeypatch.setattr(core.h.db, "ping", down)
    status = await start(core)
    assert (
        status.run is not None and status.run.state is StartupRunState.BLOCKED and status.run.blocked_on == ["database"]
    )
    assert stage(status, "database").state is StartupStageState.FAILED
    assert core.c.autonomy.mode is AutonomyMode.OFF


async def test_a_terminal_not_connected_to_its_server_blocks_the_start(h: Harness) -> None:
    core = await make(h)
    core.terminal.terminal_connected = False
    status = await start(core)
    assert (
        status.run is not None and status.run.state is StartupRunState.BLOCKED and status.run.blocked_on == ["terminal"]
    )
    assert core.c.autonomy.mode is AutonomyMode.OFF


async def test_an_account_that_cannot_be_connected_blocks_the_start_and_says_why(h: Harness) -> None:
    core = await make(h)
    assert core.account is not None
    await core.c.accounts.disconnect(core.account.id, force=True)
    core.terminal.initialize_fails = True
    status = await start(core)
    assert (
        status.run is not None and status.run.state is StartupRunState.BLOCKED and status.run.blocked_on == ["account"]
    )
    assert "could not be connected" in status.run.message
    assert core.c.autonomy.mode is AutonomyMode.OFF


async def test_starting_connects_the_selected_account_without_any_password(h: Harness) -> None:
    core = await make(h)
    assert core.account is not None
    await core.c.accounts.disconnect(core.account.id, force=True)
    assert core.c.accounts.session(core.account.id) is None
    status = await start(core)
    assert status.run is not None and status.run.state is StartupRunState.DONE
    assert (
        core.c.accounts.session(core.account.id) is not None and await core.c.credentials.has(core.account.id) is False
    )


async def test_the_terminal_on_another_account_blocks_the_start(h: Harness) -> None:
    from trading_os.infrastructure.mt5.fake import FakeAccount

    core = await make(h)
    core.terminal.accounts[7_000_007] = FakeAccount(login=7_000_007, server="Exness-MT5Trial", password="x")
    core.terminal.current_login = 7_000_007
    status = await start(core)
    assert status.run is not None and status.run.state is StartupRunState.BLOCKED and "account" in status.run.blocked_on


async def test_without_an_agent_the_system_still_observes_but_confirm_is_held_back(h: Harness) -> None:
    core = await make(h, agent=False)
    status = await start(core, AutonomyMode.CONFIRM)
    assert status.run is not None and status.run.state is StartupRunState.PARTIAL
    assert status.run.reached_mode is AutonomyMode.PAPER  # OBSERVE and PAPER send nothing; CONFIRM could
    assert {"heartbeat", "kill_switch_available"} <= set(status.run.blocked_on)
    assert stage(status, "agent").state is StartupStageState.FAILED and not status.entries_authorized
    assert core.c.autonomy.mode is AutonomyMode.PAPER


async def test_an_account_whose_trading_is_switched_off_is_degraded_and_says_so(h: Harness) -> None:
    core = await make(h)
    assert core.account is not None
    await core.c.accounts.set_trading_enabled(core.account.id, False)
    status = await core.c.startup.status()
    assert stage(status, "account").state is StartupStageState.DEGRADED and status.account is not None
    assert status.account.trading_enabled is False


async def test_a_low_ceiling_keeps_the_system_in_observation(h: Harness) -> None:
    core = await make(h, max_mode=AutonomyMode.OBSERVE)
    status = await start(core, AutonomyMode.CONFIRM)
    assert (
        status.run is not None and status.run.state is StartupRunState.PARTIAL and status.run.blocked_on == ["autonomy"]
    )
    assert "ceiling" in status.run.message  # the ladder itself refuses PAPER above an OBSERVE ceiling
    assert core.c.autonomy.mode is AutonomyMode.OBSERVE and status.plan_mode is PlanMode.OBSERVE
    assert not check(status, "mode_authorized").ok and status.ceiling is AutonomyMode.OBSERVE


async def test_stale_market_data_holds_confirm_back_and_degrades_its_stage(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = await make(h)
    monkeypatch.setattr(core.c.market, "feed_status", lambda account_id, now: (False, "last new quote 95s ago"))
    status = await start(core, AutonomyMode.CONFIRM)
    assert (
        status.run is not None
        and status.run.state is StartupRunState.PARTIAL
        and "market_data_fresh" in status.run.blocked_on
    )
    assert stage(status, "market_data").state is StartupStageState.DEGRADED and not status.entries_authorized


async def test_a_risk_engine_that_is_down_holds_confirm_back(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    core = await make(h)

    async def silent(account_id: str) -> None:
        return None

    monkeypatch.setattr(core.c.risk, "evaluate", silent)
    core.c.risk.last_error = "the risk cycle failed"
    status = await start(core, AutonomyMode.CONFIRM)
    assert (
        status.run is not None
        and status.run.state is StartupRunState.PARTIAL
        and "risk_engine" in status.run.blocked_on
    )
    assert stage(status, "risk").state is StartupStageState.FAILED


async def test_a_guardian_that_does_not_run_holds_confirm_back(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    core = await make(h)

    async def broken(account_id: str) -> int:
        raise TradingOsError("the guardian cannot run")

    monkeypatch.setattr(core.c.guardian, "guard", broken)
    status = await start(core, AutonomyMode.CONFIRM)
    assert (
        status.run is not None
        and status.run.state is StartupRunState.PARTIAL
        and "guardian_running" in status.run.blocked_on
    )
    assert stage(status, "guardian").state is StartupStageState.DEGRADED and not check(status, "guardian_running").ok


async def test_an_unresolved_unknown_command_holds_confirm_back(h: Harness) -> None:
    from tests.support.builders import make_command
    from trading_os.domain.execution.commands import CommandState

    core = await make(h)
    assert core.account is not None
    command = make_command("cmd-doubt-1", account_id=core.account.id, state=CommandState.UNKNOWN)
    await h.repos.execution.insert(command, h.clock.now())
    status = await start(core, AutonomyMode.CONFIRM)
    assert status.run is not None and status.run.state is StartupRunState.PARTIAL
    assert not check(status, "no_unknown_commands").ok and "no_unknown_commands" in status.run.blocked_on


async def test_risk_limits_and_the_initial_capital_must_be_loaded(h: Harness) -> None:
    core = await make(h)
    status = await start(core)
    ok = check(status, "risk_limits_loaded")
    assert ok.ok and "daily" in ok.detail and "weekly" in ok.detail and "capital" in ok.detail


# ------------------------------------------------------------------------------------------------------ halted


async def test_a_halted_system_does_not_start_until_the_halt_is_acknowledged(h: Harness) -> None:
    core = await make(h)
    await core.c.autonomy.halt("test", actor="user")
    status = await start(core)
    assert (
        status.run is not None and status.run.state is StartupRunState.BLOCKED and status.run.blocked_on == ["autonomy"]
    )
    assert status.halted and status.plan_mode is PlanMode.HALTED and not status.can_start
    assert (
        stage(status, "strategy").state is StartupStageState.HALTED
        and stage(status, "autonomy").state is StartupStageState.HALTED
    )
    assert stage(status, "trading").state is StartupStageState.HALTED and not status.entries_authorized
    # the guardian keeps watching what is open: halting is not "stop looking"
    assert stage(status, "guardian").state in {StartupStageState.RUNNING, StartupStageState.DEGRADED}


# ------------------------------------------------------------------------------------------------------ a real account


async def test_a_real_account_shows_the_banner_and_needs_an_explicit_confirmation_to_go_further(h: Harness) -> None:
    core = await make(h, environment=Environment.LIVE)
    status = await core.c.startup.status()
    assert status.real_account and status.real_account_banner == REAL_ACCOUNT_BANNER
    assert status.account is not None and status.account.environment is Environment.LIVE

    with pytest.raises(Forbidden) as refused:
        await core.c.startup.begin(AutonomyMode.CONFIRM)  # LIVE_CONFIRM: orders become possible
    assert refused.value.code == "real_account_confirmation_required"
    assert core.c.autonomy.mode is AutonomyMode.OFF

    observing = await start(core)  # watching is not trading: no confirmation needed
    assert observing.run is not None and observing.run.state is StartupRunState.DONE

    confirmed = await start(core, AutonomyMode.CONFIRM, acknowledge_real_account=True)
    assert (
        confirmed.plan_mode is PlanMode.LIVE_CONFIRM
        and confirmed.run is not None
        and confirmed.run.state is StartupRunState.DONE
    )


async def test_authorising_automatic_trading_is_a_separate_one_rung_gesture_green_then(h: Harness) -> None:
    core = await make(h)
    with pytest.raises(ValidationFailed) as early:
        await core.c.startup.authorize_automatic()  # OFF: nothing to authorise yet
    assert early.value.code == "not_a_step_up"

    await start(core, AutonomyMode.CONFIRM)
    mode, plan = await core.c.startup.authorize_automatic()
    assert (mode, plan) == (AutonomyMode.ARMED, PlanMode.DEMO_AUTO)
    assert core.c.autonomy.mode is AutonomyMode.ARMED  # one rung — AUTONOMOUS is another gesture
    status = await core.c.startup.status()
    assert status.plan_mode is PlanMode.DEMO_AUTO and status.next_automatic_mode is AutonomyMode.AUTONOMOUS


async def test_authorising_automatic_trading_is_refused_when_a_condition_is_red(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = await make(h)
    await start(core, AutonomyMode.CONFIRM)
    monkeypatch.setattr(core.c.market, "feed_status", lambda account_id, now: (False, "stale"))
    with pytest.raises(Forbidden) as refused:
        await core.c.startup.authorize_automatic()
    assert refused.value.code == "not_ready" and refused.value.details["blockers"] == ["market_data_fresh"]
    assert core.c.autonomy.mode is AutonomyMode.CONFIRM
    status = await core.c.startup.status()
    assert not status.can_authorize_automatic and "market_data_fresh" in status.authorize_blockers


async def test_authorising_live_auto_needs_the_explicit_confirmation_of_the_trader(h: Harness) -> None:
    core = await make(h, environment=Environment.LIVE)
    await start(core, AutonomyMode.CONFIRM, acknowledge_real_account=True)
    with pytest.raises(Forbidden) as refused:
        await core.c.startup.authorize_automatic()
    assert refused.value.code == "real_account_confirmation_required" and core.c.autonomy.mode is AutonomyMode.CONFIRM
    mode, plan = await core.c.startup.authorize_automatic(acknowledge_real_account=True)
    assert (mode, plan) == (AutonomyMode.ARMED, PlanMode.LIVE_AUTO)


# ------------------------------------------------------------------------------------------------------ the configuration screen


async def test_the_account_panel_has_what_the_configuration_screen_needs_and_no_secret(h: Harness) -> None:
    core = await make(h)
    status = await core.c.startup.status()
    panel = status.account
    assert panel is not None
    assert (panel.provider, panel.server, panel.environment.value, panel.currency) == (
        "EXNESS",
        "Exness-MT5Trial",
        "DEMO",
        "USD",
    )
    assert panel.login_masked == "****0001" and panel.connected and panel.status == "CONNECTED"
    assert panel.balance == 10_000 and panel.equity == 10_000 and panel.trading_enabled and panel.agent_connected
    assert panel.ceiling is AutonomyMode.AUTONOMOUS
    blob = panel.model_dump_json().lower()
    assert "password" not in blob and "1000001" not in panel.login_masked


async def test_the_audit_trail_records_the_start_and_how_it_ended(h: Harness) -> None:
    core = await make(h)
    await start(core)
    types = core.recorder.types()
    assert "system.start_requested" in types and "system.start_finished" in types
    finished = core.recorder.of(__import__("trading_os.domain.events", fromlist=["x"]).SystemStartFinished)[0]
    assert finished.outcome == "done" and finished.reached_mode is AutonomyMode.OBSERVE
