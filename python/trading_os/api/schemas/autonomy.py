"""The autonomy routes' models: the gestures a human makes on the ladder, and what the brake answers."""

from __future__ import annotations

from pydantic import Field

from trading_os.api.schemas.common import StrictRequest
from trading_os.domain.autonomy.state import AutonomyMode, AutonomyState
from trading_os.domain.primitives import DomainModel
from trading_os.domain.risk.lockout import ActiveLockout


class ArmRequest(StrictRequest):
    """Climb to ``target`` — exactly one rung above the current mode, never above the ceiling."""

    target: AutonomyMode


class DisarmRequest(StrictRequest):
    """Step down. From HALTED the only exit is ``acknowledge: true``, and it lands on OFF."""

    target: AutonomyMode = AutonomyMode.OBSERVE
    acknowledge: bool = False
    reason: str | None = Field(default=None, max_length=200)


class HaltRequest(StrictRequest):
    reason: str = Field(default="emergency stop from the cockpit", min_length=1, max_length=200)


class HaltResult(DomainModel):
    """The halt itself always stands. The kill-switch lockout is the Risk Engine's persistent record of the gesture: it needs the
    database, so if that is down the halt is reported with a warning instead of being held back."""

    state: AutonomyState
    kill_switch: ActiveLockout | None = None
    warnings: list[str] = Field(default_factory=list)
