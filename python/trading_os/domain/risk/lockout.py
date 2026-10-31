"""The lockout ledger is the source of truth for « locked right now » — never re-derived purely from live gate
evaluation (a missing event or a shifted day boundary could otherwise silently undo it). Pure decision points around
that ledger; the caller (``RiskService``) owns persistence and publication. Port of ``lib/risk/lockout.ts``.

Reason strings are stored in ``risk_lockouts.reason`` and compared by ``cleared_by_for_ack``: they are part of the
data contract, hence unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from trading_os.domain.primitives import DomainModel
from trading_os.domain.risk.state import GateResult, RiskMode, RiskState

KILL_SWITCH_REASON = "Kill switch manuel"
CONSECUTIVE_LOSS_REASON = "Pertes consécutives"
CONSECUTIVE_LOSS_GATE_ID = "gate-consec-loss"


class ActiveLockout(DomainModel):
    lockout_id: str
    reason: str
    since: datetime
    until: datetime | None = None  # None = acknowledgement required; set = auto-expires (T02b pause)


class LockoutWindow(DomainModel):
    """A lockout as recorded, active or not — what the compliance review replays against the trades."""

    lockout_id: str
    reason: str
    since: datetime
    until: datetime | None = None
    cleared_at: datetime | None = None


class NewLockout(DomainModel):
    reason: str
    until: datetime | None = None


def detect_new_lockout(state: RiskState, active: ActiveLockout | None) -> NewLockout | None:
    """Edge-triggered: fires only the moment a freshly computed state crosses into locked while no lockout is on
    record — never on every evaluation while already locked (it would spam duplicate ledger rows)."""
    if state.mode is not RiskMode.LOCKED or active is not None:
        return None
    return NewLockout(reason=state.lockout_reason or "locked")


def is_lockout_expired(active: ActiveLockout, now: datetime) -> bool:
    """An auto-expiring pause whose clock ran out. An acknowledgement-only lockout is never « expired »."""
    return active.until is not None and active.until <= now


def apply_active_lockout(state: RiskState, active: ActiveLockout | None, now: datetime) -> RiskState:
    """The ledger overrides live computation whenever it says locked: even if gates recover on their own the stored
    lock holds until cleared. An expired timed pause passes through unchanged (the caller still clears the row)."""
    if active is None or is_lockout_expired(active, now):
        return state
    return state.model_copy(
        update={
            "mode": RiskMode.LOCKED,
            "lockout_reason": active.reason,
            "lockout_until": active.until,
            "lockout_id": active.lockout_id,
        }
    )


def detect_consecutive_loss_pause(
    state: RiskState, active: ActiveLockout | None, last_loss_at: datetime | None, pause_minutes: int
) -> NewLockout | None:
    """The second hard lockout source: fires only on the consecutive-loss gate breach, edge-triggered (a further
    loss during the pause does not extend it)."""
    if active is not None or last_loss_at is None:
        return None
    gate: GateResult | None = next((g for g in state.gates if g.gate_id == CONSECUTIVE_LOSS_GATE_ID), None)
    if gate is None or not gate.blocked:
        return None
    return NewLockout(reason=CONSECUTIVE_LOSS_REASON, until=last_loss_at + timedelta(minutes=pause_minutes))


def cleared_by_for_ack(reason: str) -> str:
    """Every untimed lockout needs an explicit acknowledgement to clear (T02c); only the audit value differs."""
    return "kill-switch-ack" if reason == KILL_SWITCH_REASON else "manual"
