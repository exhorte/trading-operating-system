"""Risk state read by the cockpit: posture, usage against limits, and one result per gate."""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Literal

from trading_os.domain.primitives import AccountId, DomainModel


class RiskMode(StrEnum):
    NORMAL = "normal"
    WARNING = "warning"
    LOCKED = "locked"


class GateResult(DomainModel):
    """One safety gate; ``detail`` is the human-readable explanation (audit trail and cockpit)."""

    gate_id: str
    label: str
    state: Literal["open", "blocked"]
    detail: str

    @property
    def blocked(self) -> bool:
        return self.state == "blocked"


class RiskState(DomainModel):
    account_id: AccountId
    mode: RiskMode
    daily_loss_used_percent: float
    max_drawdown_used_percent: float
    open_risk_percent: float
    correlated_exposure_percent: float = 0.0
    trades_today: int | None  # None = unknown (no trade history), never a guessed zero
    consecutive_losses: int | None
    lockout_reason: str | None = None  # set unless mode == locked is false
    lockout_until: datetime | None = None
    lockout_id: str | None = None  # the ledger row that holds the lock; None when the lock is only the live gates'
    gates: list[GateResult]
    evaluated_at: datetime


def round_half_up(value: float, digits: int) -> float:
    """``Math.round`` semantics of the TypeScript engine (half goes up), not Python's banker's rounding."""
    factor = 10**digits
    return float(math.floor(value * factor + 0.5) / factor)
