"""The state of a terminal's deployment (ADR 0039 § 3): a pure function of what is observed, a frozen table of transitions, and a journal.

The launcher never produces a state above ``EA_READY`` — there is no value for it to produce (``CONFIRM``, ``ARMED`` and ``AUTONOMOUS`` are not states
of this machine). ``EA_READY`` is reachable only from ``EA_VALIDATING``: after any new hello the terminal goes through ``EA_CONNECTED`` and
``EA_VALIDATING`` again, so the reconciliation is done again.
"""

from __future__ import annotations

from datetime import timedelta
from itertools import product

import pytest

from tests.unit.launcher.support import T0
from trading_os.launcher.mt5.model import OperationKind, OperationState
from trading_os.launcher.mt5.states import (
    TRANSITIONS,
    DeploymentState,
    StateDecision,
    StateFacts,
    is_allowed,
    synthesize,
)

S = DeploymentState


def facts(**changes: object) -> StateFacts:
    base: dict[str, object] = {
        "registered": True,
        "deployed": True,
        "operation": OperationState(),
        "now": T0,
        "terminal_running": False,
        "core_reachable": True,
        "hello_received": False,
        "verdict": None,
        "block_codes": (),
        "last_state": None,
    }
    base.update(changes)
    return StateFacts(**base)  # type: ignore[arg-type]


def operating(kind: OperationKind, *, overdue: bool = False) -> OperationState:
    return OperationState(
        kind=kind,
        deployment_id="d1",
        step="x",
        started_at=T0 - timedelta(seconds=30),
        deadline=T0 - timedelta(seconds=1) if overdue else T0 + timedelta(seconds=60),
    )


# ------------------------------------------------------------------------------------------------ the table


EXPECTED = {
    S.NOT_INSTALLED: {S.DEPLOYING},
    S.DEPLOYING: {S.DEPLOYED, S.EA_ERROR},
    S.DEPLOYED: {S.TERMINAL_STARTING, S.DEPLOYING},
    S.TERMINAL_STARTING: {S.EA_LOADING, S.EA_ERROR},
    S.EA_LOADING: {S.EA_CONNECTED, S.EA_ERROR},
    S.EA_CONNECTED: {S.EA_VALIDATING, S.EA_BLOCKED, S.EA_DISCONNECTED},
    S.EA_VALIDATING: {S.EA_READY, S.EA_BLOCKED, S.EA_DISCONNECTED},
    S.EA_READY: {S.EA_VALIDATING, S.EA_BLOCKED, S.EA_DISCONNECTED, S.TERMINAL_STOPPING},
    S.EA_BLOCKED: {S.EA_VALIDATING, S.EA_DISCONNECTED, S.TERMINAL_STOPPING, S.DEPLOYING},
    S.EA_DISCONNECTED: {S.EA_CONNECTED, S.TERMINAL_STOPPING, S.DEPLOYED, S.EA_ERROR},
    S.EA_ERROR: {S.DEPLOYING, S.TERMINAL_STARTING, S.TERMINAL_STOPPING, S.DEPLOYED, S.NOT_INSTALLED},
    S.TERMINAL_STOPPING: {S.DEPLOYED, S.EA_ERROR},
}


def test_the_table_is_the_one_of_the_adr_and_nothing_else() -> None:
    assert {state: set(targets) for state, targets in TRANSITIONS.items()} == EXPECTED


@pytest.mark.parametrize(("source", "target"), list(product(S, S)))
def test_every_pair_is_allowed_exactly_when_the_table_says_so(source: DeploymentState, target: DeploymentState) -> None:
    assert is_allowed(source, target) is (target in EXPECTED[source])


def test_the_machine_has_no_state_above_ready() -> None:
    names = {state.value for state in S}
    assert not names & {"CONFIRM", "ARMED", "AUTONOMOUS", "AUTONOMOUS_RUNNING", "LIVE"}
    assert S.EA_READY in names or S.EA_READY.value in names


# ------------------------------------------------------------------------------------------------ what is observed


def test_a_terminal_that_is_not_registered_is_not_installed() -> None:
    assert synthesize(facts(registered=False)).state is S.NOT_INSTALLED


def test_a_registered_terminal_without_a_deployed_agent_is_not_installed() -> None:
    decision = synthesize(facts(deployed=False))
    assert decision.state is S.NOT_INSTALLED and "EA_NOT_DEPLOYED" in decision.codes


def test_a_deployed_agent_in_a_stopped_terminal_is_deployed() -> None:
    assert synthesize(facts()).state is S.DEPLOYED


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (OperationKind.DEPLOYING, S.DEPLOYING),
        (OperationKind.TERMINAL_STOPPING, S.TERMINAL_STOPPING),
        (OperationKind.TERMINAL_STARTING, S.TERMINAL_STARTING),
        (OperationKind.EA_LOADING, S.EA_LOADING),
    ],
)
def test_an_operation_in_progress_is_the_state(kind: OperationKind, expected: DeploymentState) -> None:
    assert synthesize(facts(operation=operating(kind))).state is expected


@pytest.mark.parametrize("kind", [k for k in OperationKind if k is not OperationKind.IDLE])
def test_an_operation_past_its_deadline_is_an_error_never_resumed(kind: OperationKind) -> None:
    decision = synthesize(facts(operation=operating(kind, overdue=True)))
    assert decision.state is S.EA_ERROR and "LAUNCHER_OPERATION_INTERRUPTED" in decision.codes


def test_a_hello_after_the_loading_began_is_connected_first() -> None:
    decision = synthesize(
        facts(
            operation=operating(OperationKind.EA_LOADING),
            terminal_running=True,
            hello_received=True,
            last_state=S.EA_LOADING,
        )
    )
    assert decision.state is S.EA_CONNECTED and not decision.anomaly


def test_a_ready_verdict_is_ready_only_after_validating() -> None:
    running = {"terminal_running": True, "hello_received": True, "verdict": "READY"}
    assert synthesize(facts(**running, last_state=S.EA_CONNECTED)).state is S.EA_VALIDATING
    assert synthesize(facts(**running, last_state=S.EA_VALIDATING)).state is S.EA_READY
    assert synthesize(facts(**running, last_state=S.EA_READY)).state is S.EA_READY
    assert synthesize(facts(**running, last_state=S.EA_BLOCKED)).state is S.EA_VALIDATING


def test_a_reconnection_goes_through_connected_and_validating_again() -> None:
    running = {"terminal_running": True, "hello_received": True, "verdict": "READY"}
    gone = synthesize(facts(terminal_running=True, hello_received=False, last_state=S.EA_READY))
    assert gone.state is S.EA_DISCONNECTED
    back = synthesize(facts(**running, last_state=S.EA_DISCONNECTED))
    assert back.state is S.EA_CONNECTED
    assert synthesize(facts(**running, last_state=S.EA_CONNECTED)).state is S.EA_VALIDATING
    assert synthesize(facts(**running, last_state=S.EA_VALIDATING)).state is S.EA_READY


def test_a_blocked_verdict_carries_the_exact_codes() -> None:
    decision = synthesize(
        facts(
            terminal_running=True,
            hello_received=True,
            verdict="BLOCKED",
            block_codes=("PRODUCT_UNDECLARED", "ACCOUNT_IDENTITY_UNVERIFIED"),
            last_state=S.EA_VALIDATING,
        )
    )
    assert decision.state is S.EA_BLOCKED and decision.codes == ("PRODUCT_UNDECLARED", "ACCOUNT_IDENTITY_UNVERIFIED")


def test_a_validating_verdict_is_validating() -> None:
    decision = synthesize(
        facts(terminal_running=True, hello_received=True, verdict="VALIDATING", last_state=S.EA_CONNECTED)
    )
    assert decision.state is S.EA_VALIDATING


def test_an_agent_that_was_there_and_is_gone_is_disconnected() -> None:
    for before in (S.EA_CONNECTED, S.EA_VALIDATING, S.EA_READY, S.EA_BLOCKED):
        assert (
            synthesize(facts(terminal_running=True, hello_received=False, last_state=before)).state is S.EA_DISCONNECTED
        )


def test_a_core_that_cannot_be_asked_is_not_a_hello() -> None:
    decision = synthesize(
        facts(terminal_running=True, hello_received=None, core_reachable=False, last_state=S.EA_READY)
    )
    assert decision.state is S.EA_DISCONNECTED and "CORE_UNREACHABLE" in decision.codes


def test_a_terminal_running_with_no_agent_report_is_deployed_and_says_so() -> None:
    decision = synthesize(facts(terminal_running=True, hello_received=False))
    assert decision.state is S.DEPLOYED and "TERMINAL_RUNNING_NO_EA_REPORT" in decision.codes


def test_an_error_stays_while_the_terminal_runs_and_ends_when_it_stops() -> None:
    assert synthesize(facts(terminal_running=True, last_state=S.EA_ERROR)).state is S.EA_ERROR
    assert synthesize(facts(terminal_running=False, last_state=S.EA_ERROR)).state is S.DEPLOYED


def test_a_jump_the_table_does_not_know_is_a_fact_not_a_refusal_and_is_flagged() -> None:
    """A terminal started by hand, an agent that appears on its own: the state follows what is seen, and the oddity is recorded."""
    decision = synthesize(
        facts(terminal_running=True, hello_received=True, verdict="BLOCKED", block_codes=("X",), last_state=S.DEPLOYED)
    )
    assert decision.state is S.EA_BLOCKED and decision.anomaly
    ready = synthesize(facts(terminal_running=True, hello_received=True, verdict="READY", last_state=S.DEPLOYED))
    assert ready.state is not S.EA_READY and ready.anomaly, "a jump never lands on ready"


def test_the_decision_is_a_value() -> None:
    assert isinstance(synthesize(facts()), StateDecision)
