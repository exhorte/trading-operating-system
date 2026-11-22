"""The state of a terminal's deployment (ADR 0039 § 3) — a pure function of what is observed, and a frozen table of transitions.

Nothing here is a stored truth: the preparation is recomputed at every observation. The one thing kept is the *last state seen* — to check the table and to
recognise a disconnection — and it is never read as proof of readiness. ``EA_READY`` is reachable only from ``EA_VALIDATING``: after any new hello the
terminal is ``EA_CONNECTED`` and then ``EA_VALIDATING`` again, so the reconciliation of the attachment is done again. A jump the table does not know is a
*fact* (a terminal started by hand, an agent that appears on its own): it is not refused, it is flagged, and a jump never lands on ``EA_READY``.

The machine stops at ``EA_READY``: ``CONFIRM``, ``ARMED`` and ``AUTONOMOUS`` are not states of it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from trading_os.domain.primitives import DomainModel
from trading_os.launcher.mt5.model import OperationKind, OperationState, is_overdue


class DeploymentState(StrEnum):
    NOT_INSTALLED = "NOT_INSTALLED"
    DEPLOYING = "DEPLOYING"
    DEPLOYED = "DEPLOYED"
    TERMINAL_STOPPING = "TERMINAL_STOPPING"
    TERMINAL_STARTING = "TERMINAL_STARTING"
    EA_LOADING = "EA_LOADING"
    EA_CONNECTED = "EA_CONNECTED"
    EA_VALIDATING = "EA_VALIDATING"
    EA_READY = "EA_READY"
    EA_BLOCKED = "EA_BLOCKED"
    EA_DISCONNECTED = "EA_DISCONNECTED"
    EA_ERROR = "EA_ERROR"


S = DeploymentState

TRANSITIONS: dict[DeploymentState, frozenset[DeploymentState]] = {
    S.NOT_INSTALLED: frozenset({S.DEPLOYING}),
    S.DEPLOYING: frozenset({S.DEPLOYED, S.EA_ERROR}),
    S.DEPLOYED: frozenset({S.TERMINAL_STARTING, S.DEPLOYING}),
    S.TERMINAL_STARTING: frozenset({S.EA_LOADING, S.EA_ERROR}),
    S.EA_LOADING: frozenset({S.EA_CONNECTED, S.EA_ERROR}),
    S.EA_CONNECTED: frozenset({S.EA_VALIDATING, S.EA_BLOCKED, S.EA_DISCONNECTED}),
    S.EA_VALIDATING: frozenset({S.EA_READY, S.EA_BLOCKED, S.EA_DISCONNECTED}),
    S.EA_READY: frozenset({S.EA_VALIDATING, S.EA_BLOCKED, S.EA_DISCONNECTED, S.TERMINAL_STOPPING}),
    S.EA_BLOCKED: frozenset({S.EA_VALIDATING, S.EA_DISCONNECTED, S.TERMINAL_STOPPING, S.DEPLOYING}),
    S.EA_DISCONNECTED: frozenset({S.EA_CONNECTED, S.TERMINAL_STOPPING, S.DEPLOYED, S.EA_ERROR}),
    S.EA_ERROR: frozenset({S.DEPLOYING, S.TERMINAL_STARTING, S.TERMINAL_STOPPING, S.DEPLOYED, S.NOT_INSTALLED}),
    S.TERMINAL_STOPPING: frozenset({S.DEPLOYED, S.EA_ERROR}),
}

CONNECTED_FAMILY = frozenset({S.EA_CONNECTED, S.EA_VALIDATING, S.EA_READY, S.EA_BLOCKED})


def is_allowed(source: DeploymentState, target: DeploymentState) -> bool:
    return target in TRANSITIONS[source]


class StateFacts(DomainModel):
    """What the synthesis is given. ``hello_received`` is ``None`` when the core could not be asked: that is not a hello and not an absence."""

    registered: bool
    deployed: bool
    operation: OperationState
    now: datetime
    terminal_running: bool
    core_reachable: bool
    hello_received: bool | None
    verdict: str | None = (
        None  # READY / VALIDATING / BLOCKED — the core's reading of the conditions, when there is a hello
    )
    block_codes: tuple[str, ...] = ()
    last_state: DeploymentState | None = None


class StateDecision(DomainModel):
    state: DeploymentState
    codes: tuple[str, ...] = ()
    anomaly: bool = False


def synthesize(facts: StateFacts) -> StateDecision:
    if not facts.registered:
        return StateDecision(state=S.NOT_INSTALLED, codes=("TERMINAL_NOT_REGISTERED",))
    operation = facts.operation
    if operation.kind is not OperationKind.IDLE:
        if is_overdue(operation, facts.now):
            return StateDecision(state=S.EA_ERROR, codes=("LAUNCHER_OPERATION_INTERRUPTED",))
        loading = operation.kind is OperationKind.EA_LOADING
        if not (loading and facts.hello_received):
            return StateDecision(state=_OPERATION_STATES[operation.kind])
    elif not facts.deployed:
        return StateDecision(state=S.NOT_INSTALLED, codes=("EA_NOT_DEPLOYED",))
    if facts.hello_received:
        return _with_hello(facts)
    return _without_hello(facts)


_OPERATION_STATES = {
    OperationKind.DEPLOYING: S.DEPLOYING,
    OperationKind.TERMINAL_STOPPING: S.TERMINAL_STOPPING,
    OperationKind.TERMINAL_STARTING: S.TERMINAL_STARTING,
    OperationKind.EA_LOADING: S.EA_LOADING,
}


def _without_hello(facts: StateFacts) -> StateDecision:
    last = facts.last_state
    if last in CONNECTED_FAMILY:
        code = "CORE_UNREACHABLE" if not facts.core_reachable else "AGENT_GONE"
        return StateDecision(state=S.EA_DISCONNECTED, codes=(code,))
    if last is S.EA_DISCONNECTED and facts.terminal_running:
        return StateDecision(state=S.EA_DISCONNECTED, codes=("AGENT_GONE",))
    if last is S.EA_ERROR and facts.terminal_running:
        return StateDecision(state=S.EA_ERROR, codes=("EA_ERROR_STANDS",))
    return StateDecision(state=S.DEPLOYED, codes=("TERMINAL_RUNNING_NO_EA_REPORT",) if facts.terminal_running else ())


def _with_hello(facts: StateFacts) -> StateDecision:
    last = facts.last_state
    codes: tuple[str, ...] = ()
    if facts.verdict == "BLOCKED":
        target, codes = S.EA_BLOCKED, facts.block_codes
    elif facts.verdict == "READY":
        target = S.EA_READY
    else:
        target = S.EA_VALIDATING
    if last is None or last in (S.EA_LOADING, S.EA_DISCONNECTED):
        return StateDecision(
            state=S.EA_CONNECTED, codes=("HELLO_RECEIVED",)
        )  # the first step of an attachment, whatever the verdict
    if last in CONNECTED_FAMILY:
        if target is S.EA_READY and not is_allowed(last, S.EA_READY) and last is not S.EA_READY:
            return StateDecision(state=S.EA_VALIDATING)
        if last is target or is_allowed(last, target):
            return StateDecision(state=target, codes=codes)
        return StateDecision(state=target, codes=codes, anomaly=True)
    # a hello where the machine did not expect one: a fact, flagged, and never straight to ready
    shown = S.EA_VALIDATING if target is S.EA_READY else target
    return StateDecision(state=shown, codes=codes, anomaly=True)
