"""What the cockpit and the API read about autonomy in one piece."""

from __future__ import annotations

from trading_os.domain.autonomy.readiness import ReadinessReport
from trading_os.domain.autonomy.state import AutonomyMode, AutonomyState
from trading_os.domain.primitives import DomainModel


class AutonomyOverview(DomainModel):
    state: AutonomyState
    ceiling: AutonomyMode  # the highest rung reachable now: min(TRADING_MODE, the active account's max_mode)
    effective_mode: AutonomyMode  # what the active account is really in: the lower of the state and its ceiling
    active_account_id: str | None = None
    readiness: ReadinessReport | None = None
