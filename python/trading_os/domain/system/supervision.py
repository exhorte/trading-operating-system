"""Supervision policy (mission § 26): what to do about a fault, as a table — not scattered ``if`` statements.

``Finding`` is what the supervisor observed (« the agent heartbeat is stale »); ``actions_for`` maps it to the remedy,
given how far up the autonomy ladder the system currently is: a fault matters more the more it is trusted to act alone.

    SAFE       — block new entries (the risk gate answers ``system_degraded``); nothing else changes
    RECONNECT  — try to bring the link back (terminal reader, execution agent)
    RECONCILE  — compare state with MT5 now
    DISARM     — drop the autonomy mode to OBSERVE; a human must climb again
    HALT       — autonomy HALTED + local halt on the agent + incident; leaving it takes a human
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from trading_os.domain.autonomy.state import AUTOMATIC_MODES, AutonomyMode
from trading_os.domain.primitives import DomainModel


class Severity(StrEnum):
    OK = "ok"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Action(StrEnum):
    SAFE = "SAFE"
    RECONNECT = "RECONNECT"
    RECONCILE = "RECONCILE"
    DISARM = "DISARM"
    HALT = "HALT"


class Finding(DomainModel):
    code: str
    component: str
    severity: Severity
    detail: str
    observed_at: datetime
    persisting: bool = False  # the fault has outlived the grace period of its first remedy
    account_id: str | None = None  # None = about the core as a whole, not one account


# code → actions that always apply. ``automatic_extra`` adds actions when the system is ARMED/AUTONOMOUS.
_POLICY: dict[str, tuple[tuple[Action, ...], tuple[Action, ...]]] = {
    "stale_market_data": ((Action.SAFE,), ()),
    "mt5_disconnected": ((Action.RECONNECT, Action.SAFE), ()),
    "agent_heartbeat_stale": ((Action.SAFE,), (Action.DISARM,)),
    "database_unavailable": ((Action.SAFE,), (Action.HALT,)),
    "execution_failure": ((Action.SAFE, Action.RECONCILE), ()),
    "unknown_command": ((Action.SAFE, Action.RECONCILE), ()),
    "reconciliation_failed": ((Action.RECONCILE,), ()),
    "unexpected_position": ((Action.HALT,), ()),
    "critical_error": ((Action.HALT,), ()),
}


def actions_for(finding: Finding, mode: AutonomyMode) -> list[Action]:
    """Remedies for one finding, most protective last-resort included, without duplicates and in a stable order."""
    if finding.severity is Severity.OK:
        return []
    automatic = mode in AUTOMATIC_MODES
    always, extra = _POLICY.get(finding.code, _generic(finding.severity))
    actions = list(always) + (list(extra) if automatic else [])
    # A fault that outlives its first remedy is escalated.
    if finding.persisting:
        if finding.code == "mt5_disconnected" and automatic:
            actions.append(Action.DISARM)
        if finding.code == "reconciliation_failed":
            actions.append(Action.HALT)
    if finding.severity is Severity.CRITICAL and Action.HALT not in actions:
        actions.append(Action.HALT)
    return list(dict.fromkeys(actions))


def _generic(severity: Severity) -> tuple[tuple[Action, ...], tuple[Action, ...]]:
    if severity is Severity.CRITICAL:
        return (Action.HALT,), ()
    if severity is Severity.HIGH:
        return (Action.SAFE,), (Action.DISARM,)
    return (Action.SAFE,), ()


def worst(findings: list[Finding]) -> Severity:
    order = [Severity.OK, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
    return max((f.severity for f in findings), key=order.index, default=Severity.OK)


def is_stale(last_seen: datetime | None, now: datetime, max_age_seconds: float) -> bool:
    """Never seen counts as stale — a component that has not spoken yet is not healthy."""
    return last_seen is None or (now - last_seen).total_seconds() > max_age_seconds
