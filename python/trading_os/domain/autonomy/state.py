"""The autonomy ladder and its transitions (ADR 0014/0015, mission § 24).

    OFF → OBSERVE → PAPER → CONFIRM → ARMED → AUTONOMOUS          (+ HALTED, reachable from anywhere)

* **One rung up at a time**, never above the ceiling (``min(TRADING_MODE, account max_mode)``, default OBSERVE).
* Going down is always allowed and immediate.
* ``ARMED`` and ``AUTONOMOUS`` need a green readiness report; ``ARMED`` lives under a lease the server renews —
  when it lapses the system falls back to CONFIRM (a human is back in the loop), it does not halt.
* ``HALTED`` is the only state a critical error can produce from ARMED/AUTONOMOUS; leaving it takes an explicit
  human acknowledgement and lands on OFF — never straight back to trading.

Pure functions over an immutable ``AutonomyState``: the service persists and publishes, this module decides.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from trading_os.domain.primitives import DomainModel
from trading_os.shared.errors import Forbidden, IllegalTransition


class AutonomyMode(StrEnum):
    OFF = "OFF"
    OBSERVE = "OBSERVE"
    PAPER = "PAPER"
    CONFIRM = "CONFIRM"
    ARMED = "ARMED"
    AUTONOMOUS = "AUTONOMOUS"
    HALTED = "HALTED"


LADDER: tuple[AutonomyMode, ...] = (
    AutonomyMode.OFF,
    AutonomyMode.OBSERVE,
    AutonomyMode.PAPER,
    AutonomyMode.CONFIRM,
    AutonomyMode.ARMED,
    AutonomyMode.AUTONOMOUS,
)

# Modes that send orders without a human gesture per order — they need readiness.
AUTOMATIC_MODES = frozenset({AutonomyMode.ARMED, AutonomyMode.AUTONOMOUS})

DEFAULT_LEASE = timedelta(minutes=30)


def rank(mode: AutonomyMode) -> int:
    """Position on the ladder; HALTED ranks below OFF (it permits nothing)."""
    return LADDER.index(mode) if mode is not AutonomyMode.HALTED else -1


def lowest(*modes: AutonomyMode) -> AutonomyMode:
    return min(modes, key=rank)


class ExecutionRoute(StrEnum):
    """What happens to an approved intent in a given mode."""

    NONE = "none"  # recorded only (OFF, OBSERVE, HALTED)
    PAPER = "paper"  # simulated fill in process, never MT5
    CONFIRM = "confirm"  # waits for a human, then goes to the execution agent
    AUTOMATIC = "automatic"  # goes to the execution agent without a per-order gesture


def route_for(mode: AutonomyMode) -> ExecutionRoute:
    return {
        AutonomyMode.PAPER: ExecutionRoute.PAPER,
        AutonomyMode.CONFIRM: ExecutionRoute.CONFIRM,
        AutonomyMode.ARMED: ExecutionRoute.AUTOMATIC,
        AutonomyMode.AUTONOMOUS: ExecutionRoute.AUTOMATIC,
    }.get(mode, ExecutionRoute.NONE)


class Transition(DomainModel):
    from_mode: AutonomyMode
    to_mode: AutonomyMode
    at: datetime
    reason: str


class AutonomyState(DomainModel):
    mode: AutonomyMode = AutonomyMode.OFF
    since: datetime
    lease_until: datetime | None = None  # ARMED only
    halted_reason: str | None = None
    last_transition: Transition | None = None

    @property
    def evaluates_strategies(self) -> bool:
        return self.mode not in {AutonomyMode.OFF, AutonomyMode.HALTED}

    @property
    def permits_entries(self) -> bool:
        """Whether new entries may reach an executor at all (paper included)."""
        return route_for(self.mode) is not ExecutionRoute.NONE


def initial_state(now: datetime) -> AutonomyState:
    """The system always starts OFF — never armed, whatever it was before the restart (ADR 0014)."""
    return AutonomyState(mode=AutonomyMode.OFF, since=now)


def _moved(state: AutonomyState, to: AutonomyMode, now: datetime, reason: str, **changes: object) -> AutonomyState:
    base = {
        "mode": to,
        "since": now,
        "lease_until": None,
        "halted_reason": None,
        "last_transition": Transition(from_mode=state.mode, to_mode=to, at=now, reason=reason),
    }
    base.update(changes)
    return state.model_copy(update=base)


def arm(
    state: AutonomyState,
    target: AutonomyMode,
    *,
    ceiling: AutonomyMode,
    now: datetime,
    ready: bool,
    lease: timedelta = DEFAULT_LEASE,
) -> AutonomyState:
    """Climb exactly one rung to ``target``."""
    if state.mode is AutonomyMode.HALTED:
        raise IllegalTransition("the system is halted: acknowledge the halt (disarm) before climbing", code="halted")
    if target is AutonomyMode.HALTED or target not in LADDER:
        raise IllegalTransition(f"{target} is not a rung you can arm to", code="invalid_target")
    next_rung = LADDER[rank(state.mode) + 1] if rank(state.mode) + 1 < len(LADDER) else None
    if target is not next_rung:
        code = "skipped_rung" if rank(target) > rank(state.mode) else "not_a_step_up"
        raise IllegalTransition(f"{state.mode} → {target}: one rung at a time (next is {next_rung})", code=code)
    if rank(target) > rank(ceiling):
        raise Forbidden(f"{target} is above the configured ceiling ({ceiling})", code="above_ceiling")
    if target in AUTOMATIC_MODES and not ready:
        raise Forbidden("autonomy readiness is not green: automatic modes are blocked", code="not_ready")
    lease_until = now + lease if target is AutonomyMode.ARMED else None
    return _moved(state, target, now, f"armed to {target}", lease_until=lease_until)


def renew_lease(state: AutonomyState, *, now: datetime, lease: timedelta = DEFAULT_LEASE) -> AutonomyState:
    if state.mode is not AutonomyMode.ARMED:
        raise IllegalTransition("only an ARMED session has a lease", code="no_lease")
    return state.model_copy(update={"lease_until": now + lease})


def expire_lease_if_due(state: AutonomyState, now: datetime) -> AutonomyState:
    """A lapsed lease drops ARMED to CONFIRM: a human is back in the loop; nothing is halted."""
    if state.mode is AutonomyMode.ARMED and state.lease_until is not None and state.lease_until <= now:
        return _moved(state, AutonomyMode.CONFIRM, now, "lease expired")
    return state


def disarm(
    state: AutonomyState, *, now: datetime, target: AutonomyMode = AutonomyMode.OBSERVE, acknowledge: bool = False
) -> AutonomyState:
    """Step down (always allowed). From HALTED the only exit is an explicit acknowledgement, landing on OFF."""
    if state.mode is AutonomyMode.HALTED:
        if not acknowledge:
            raise Forbidden("the halt must be acknowledged explicitly", code="ack_required")
        return _moved(state, AutonomyMode.OFF, now, "halt acknowledged")
    if target is AutonomyMode.HALTED or target not in LADDER:
        raise IllegalTransition(f"{target} is not a rung you can step down to", code="invalid_target")
    if rank(target) >= rank(state.mode):
        return state  # already at or below the target: nothing to do, and never a step *up* through disarm
    return _moved(state, target, now, f"disarmed to {target}")


def halt(state: AutonomyState, *, reason: str, now: datetime) -> AutonomyState:
    """Cut everything. Idempotent: a second halt keeps the first reason."""
    if state.mode is AutonomyMode.HALTED:
        return state
    return _moved(state, AutonomyMode.HALTED, now, reason, halted_reason=reason)


def clamp_to_ceiling(state: AutonomyState, ceiling: AutonomyMode, now: datetime) -> AutonomyState:
    """If the ceiling was lowered under a running mode, come down to it."""
    if state.mode is not AutonomyMode.HALTED and rank(state.mode) > rank(ceiling):
        return _moved(state, ceiling, now, f"ceiling lowered to {ceiling}")
    return state
