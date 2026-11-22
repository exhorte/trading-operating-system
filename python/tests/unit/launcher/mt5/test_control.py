"""The controlled start of a terminal (ADR 0038 § 8, ADR 0039 §§ 3 and 5, I6). Nothing runs MetaTrader: the terminal is a process of a fake table that obeys
a close request — or does not — and the spawner adds one. A fake sleeper moves the clock, so a ninety-second wait takes no time."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.launcher.mt5.support import key
from tests.unit.launcher.mt5.support_control import EXE_NAME, Machine, ready
from tests.unit.launcher.mt5.support_deploy import TERMINAL_ID
from trading_os.launcher.events import EventType
from trading_os.launcher.mt5.control import EA_LOADING_TIMEOUT_S, StartRefused
from trading_os.launcher.mt5.model import CenterFacts, OperationKind, TerminalSnapshot
from trading_os.launcher.mt5.states import DeploymentState as S

PHRASE = f"FERMER {TERMINAL_ID}"


def states(machine: Machine) -> list[str]:
    return [
        event.diagnostic.split(" → ")[1].split(" ;")[0]
        for event in machine.world.events.read(200)
        if event.type is EventType.MT5_STATE_TRANSITION
    ]


# ------------------------------------------------------------------------------------------------ a terminal that is closed


def test_a_closed_terminal_is_started_with_the_prepared_file_and_nothing_else(tmp_path: Path) -> None:
    machine = Machine(tmp_path, running=False)
    machine.center.hello_after(3, ready())
    controller = machine.controller()
    plan = controller.plan(machine.entry())
    assert plan.problems == [] and not plan.needs_close and plan.confirmation_phrase is None
    result = controller.start(plan)
    (arguments,) = machine.spawned
    assert arguments[0] == machine.exe and arguments[1] == f"/config:{machine.entry().prepared.startup_path}"  # type: ignore[union-attr]
    assert len(arguments) == 2, "no account, no password, no server on the command line"
    assert result.state is S.EA_CONNECTED and result.hello_verified is True and not result.closed_previous
    assert machine.closed_asked == [] and machine.probe.calls == [], (
        "a closed terminal is not read and nothing is closed"
    )
    assert machine.entry().operation.kind is OperationKind.IDLE
    assert states(machine) == ["TERMINAL_STARTING", "EA_LOADING", "EA_CONNECTED"]
    assert machine.entry().last_state.state == "EA_CONNECTED"  # type: ignore[union-attr]


def test_the_planning_of_a_closed_terminal_starts_and_writes_nothing(tmp_path: Path) -> None:
    machine = Machine(tmp_path, running=False)
    before = machine.world.tree()
    machine.controller().plan(machine.entry())
    assert machine.spawned == [] and machine.world.tree() == before


# ------------------------------------------------------------------------------------------------ a terminal that is open


def test_an_open_terminal_with_no_position_is_closed_politely_after_the_typed_phrase_then_started(
    tmp_path: Path,
) -> None:
    machine = Machine(tmp_path, running=True)
    machine.center.hello_after(2, ready())
    controller = machine.controller()
    plan = controller.plan(machine.entry())
    assert plan.problems == [] and plan.needs_close and plan.confirmation_phrase == PHRASE
    assert machine.probe.calls == [machine.exe]
    result = controller.start(plan, confirmation=PHRASE)
    assert machine.closed_asked == [1872], "a polite close request to that process, nothing else"
    assert result.closed_previous and result.state is S.EA_CONNECTED
    assert states(machine) == ["TERMINAL_STOPPING", "DEPLOYED", "TERMINAL_STARTING", "EA_LOADING", "EA_CONNECTED"]
    assert [e.type for e in machine.world.events.read(200)].count(EventType.MT5_RESTART_REQUESTED) == 1


@pytest.mark.parametrize("typed", [None, "", "fermer", "FERMER", f"fermer {TERMINAL_ID}", f"{PHRASE} ", "oui", "--yes"])
def test_without_the_exact_phrase_an_open_terminal_is_never_touched(tmp_path: Path, typed: str | None) -> None:
    machine = Machine(tmp_path, running=True)
    controller = machine.controller()
    plan = controller.plan(machine.entry())
    with pytest.raises(StartRefused) as refused:
        controller.start(plan, confirmation=typed)
    assert any("FERMER" in problem for problem in refused.value.problems)
    assert machine.closed_asked == [] and machine.spawned == []
    assert machine.entry().operation.kind is OperationKind.IDLE


def test_a_terminal_holding_a_position_is_not_closed(tmp_path: Path) -> None:
    machine = Machine(tmp_path, running=True)
    machine.probe.snapshot = TerminalSnapshot(login="486046157", positions=1, orders=0)
    controller = machine.controller()
    plan = controller.plan(machine.entry())
    assert any(gate.code == "NO_OPEN_POSITIONS" and not gate.ok for gate in plan.gates)
    with pytest.raises(StartRefused):
        controller.start(plan, confirmation=PHRASE)
    assert machine.closed_asked == [] and machine.spawned == []


def test_a_terminal_holding_a_pending_order_is_not_closed(tmp_path: Path) -> None:
    machine = Machine(tmp_path, running=True)
    machine.probe.snapshot = TerminalSnapshot(login="486046157", positions=0, orders=2)
    controller = machine.controller()
    with pytest.raises(StartRefused):
        controller.start(controller.plan(machine.entry()), confirmation=PHRASE)
    assert machine.closed_asked == []


def test_a_terminal_that_cannot_be_read_is_not_closed(tmp_path: Path) -> None:
    """Fail closed: not knowing whether a position is open is not the same as none being open."""
    machine = Machine(tmp_path, running=True)
    machine.probe.error = "MetaTrader 5 n'a pas répondu"
    controller = machine.controller()
    plan = controller.plan(machine.entry())
    assert any(gate.code == "TERMINAL_READABLE" and not gate.ok for gate in plan.gates)
    with pytest.raises(StartRefused):
        controller.start(plan, confirmation=PHRASE)
    assert machine.closed_asked == []


@pytest.mark.parametrize(
    "snapshot",
    [TerminalSnapshot(login="123", positions=0, orders=0), TerminalSnapshot(login=None, positions=0, orders=0)],
)
def test_a_terminal_on_another_login_is_not_closed(tmp_path: Path, snapshot: TerminalSnapshot) -> None:
    machine = Machine(tmp_path, running=True)
    machine.probe.snapshot = snapshot
    controller = machine.controller()
    with pytest.raises(StartRefused) as refused:
        controller.start(controller.plan(machine.entry()), confirmation=PHRASE)
    assert any("LOGIN_MATCHES" in problem for problem in refused.value.problems)
    assert machine.closed_asked == []


def test_a_worker_of_the_core_attached_to_the_account_blocks_the_close_and_says_to_detach(tmp_path: Path) -> None:
    """R16: a worker that finds MetaTrader closed would start it again, without the agent."""
    machine = Machine(tmp_path, running=True)
    machine.with_workers(alive=1)
    controller = machine.controller()
    plan = controller.plan(machine.entry())
    (gate,) = [g for g in plan.gates if g.code == "CORE_WORKER_DETACHED"]
    assert not gate.ok and "détachez" in gate.detail.lower() and "ne détache ni ne rattache" in gate.detail
    with pytest.raises(StartRefused):
        controller.start(plan, confirmation=PHRASE)
    assert machine.closed_asked == []


def test_a_core_that_is_up_but_does_not_say_how_many_workers_is_a_refusal(tmp_path: Path) -> None:
    from tests.unit.launcher.support import FakeHealth, core_health

    machine = Machine(tmp_path, running=True)
    machine.health = FakeHealth(core_health(mt5_workers=None))
    plan = machine.controller().plan(machine.entry())
    assert any(g.code == "CORE_WORKER_DETACHED" and not g.ok for g in plan.gates)


def test_a_core_that_is_down_is_not_an_obstacle(tmp_path: Path) -> None:
    machine = Machine(tmp_path, running=True)
    plan = machine.controller().plan(machine.entry())
    assert next(g for g in plan.gates if g.code == "CORE_WORKER_DETACHED").ok


def test_a_terminal_that_ignores_the_close_request_is_left_alone_never_killed(tmp_path: Path) -> None:
    machine = Machine(tmp_path, running=True, obeys=False)
    controller = machine.controller()
    result = controller.start(controller.plan(machine.entry()), confirmation=PHRASE)
    assert result.state is S.EA_ERROR and "TERMINAL_CLOSE_TIMEOUT" in result.codes
    assert machine.spawned == [] and machine.running_pid == 1872
    assert machine.entry().operation.kind is OperationKind.IDLE
    # (the fake controller raises if the launcher ever tries to end a process by force)


# ------------------------------------------------------------------------------------------------ the agent does not say hello


def test_an_agent_that_stays_silent_ends_in_error_with_what_can_be_told(tmp_path: Path) -> None:
    machine = Machine(tmp_path, running=False)
    machine.world.files.experts[key(str(machine.world.data))] = False
    controller = machine.controller()
    result = controller.start(controller.plan(machine.entry()))
    assert result.state is S.EA_ERROR and result.hello_verified is False
    assert {"MT5_EA_NOT_REPORTING", "MT5_EXPERTS_DISABLED"} <= set(result.codes)
    assert any("WebRequest" in note for note in result.notes), "what only the person can check is said, not guessed"
    assert sum(machine.sleeps) >= EA_LOADING_TIMEOUT_S
    assert machine.entry().last_state.state == "EA_ERROR"  # type: ignore[union-attr]
    assert EventType.MT5_EA_NOT_REPORTING in [e.type for e in machine.world.events.read(200)]


def test_silence_without_a_proof_of_disabled_experts_does_not_claim_it(tmp_path: Path) -> None:
    machine = Machine(tmp_path, running=False)
    controller = machine.controller()
    result = controller.start(controller.plan(machine.entry()))
    assert "MT5_EXPERTS_DISABLED" not in result.codes


def test_a_core_that_cannot_be_asked_leaves_the_attachment_unverified_and_does_not_wait_in_vain(tmp_path: Path) -> None:
    machine = Machine(tmp_path, running=False)
    machine.center.facts = CenterFacts(reachable=False)
    controller = machine.controller()
    result = controller.start(controller.plan(machine.entry()))
    assert result.hello_verified is None and "CORE_UNREACHABLE" in result.codes
    assert sum(machine.sleeps) < EA_LOADING_TIMEOUT_S


def test_a_terminal_that_cannot_be_launched_is_an_error_and_the_operation_is_ended(tmp_path: Path) -> None:
    machine = Machine(tmp_path, running=False, starts=False)
    controller = machine.controller()
    result = controller.start(controller.plan(machine.entry()))
    assert result.state is S.EA_ERROR and "TERMINAL_NOT_STARTED" in result.codes
    assert machine.entry().operation.kind is OperationKind.IDLE


# ------------------------------------------------------------------------------------------------ the preconditions


def test_a_terminal_whose_agent_changed_since_deployment_is_not_started(tmp_path: Path) -> None:
    machine = Machine(tmp_path, running=False)
    (machine.world.data / "MQL5" / "Experts" / "TradingOsAgent" / "TradingOsAgent.ex5").write_bytes(
        b"someone replaced it"
    )
    controller = machine.controller()
    with pytest.raises(StartRefused) as refused:
        controller.start(controller.plan(machine.entry()))
    assert any("AGENT_DEPLOYED" in problem for problem in refused.value.problems) and machine.spawned == []


def test_a_preset_that_changed_since_preparation_is_not_started_with(tmp_path: Path) -> None:
    machine = Machine(tmp_path, running=False)
    next(machine.world.data.glob("MQL5/Presets/*.set")).write_bytes(b"edited")
    controller = machine.controller()
    with pytest.raises(StartRefused) as refused:
        controller.start(controller.plan(machine.entry()))
    assert any("PRESET_PREPARED" in problem for problem in refused.value.problems)


def test_a_terminal_that_moved_is_not_started(tmp_path: Path) -> None:
    machine = Machine(tmp_path, running=False)
    machine.world.files.origins[key(str(machine.world.data))] = r"C:\Elsewhere"
    controller = machine.controller()
    with pytest.raises(StartRefused) as refused:
        controller.start(controller.plan(machine.entry()))
    assert any("TERMINAL_IDENTITY" in problem for problem in refused.value.problems)


def test_a_second_operation_on_the_same_terminal_is_refused(tmp_path: Path) -> None:
    machine = Machine(tmp_path, running=False)
    controller = machine.controller()
    plan = controller.plan(machine.entry())
    machine.world.registry.begin_operation(
        TERMINAL_ID, OperationKind.DEPLOYING, deployment_id="x", step="y", timeout_s=60
    )
    with pytest.raises(StartRefused):
        controller.start(plan)
    assert machine.spawned == []
    assert machine.entry().operation.kind is OperationKind.DEPLOYING, "the other operation is left as it was"


def test_the_executable_is_the_terminals_own_and_the_name_is_checked(tmp_path: Path) -> None:
    """Another program called terminal64.exe elsewhere is not *this* terminal."""
    from tests.unit.launcher.support import proc

    machine = Machine(tmp_path, running=False)
    machine.table._processes.append(proc(999, name=EXE_NAME, executable=r"C:\Somewhere\Else\terminal64.exe"))
    plan = machine.controller().plan(machine.entry())
    assert not plan.needs_close
