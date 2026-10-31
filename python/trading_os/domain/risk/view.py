"""The risk read model the cockpit renders: the live state flattened with the limits it is measured against
(port of ``toRiskStatusReadModel``)."""

from __future__ import annotations

from datetime import datetime

from trading_os.domain.primitives import DomainModel
from trading_os.domain.risk.policy import RiskProfile
from trading_os.domain.risk.state import GateResult, RiskMode, RiskState


class RiskStatus(DomainModel):
    state: RiskMode
    daily_loss_limit_percent: float
    daily_loss_used_percent: float
    max_drawdown_limit_percent: float
    max_drawdown_used_percent: float
    open_risk_limit_percent: float
    open_risk_percent: float
    correlated_exposure_limit_percent: float
    correlated_exposure_percent: float
    max_trades_per_day: int
    trades_today: int | None  # None = unknown (no history), never a guessed zero
    consecutive_losses: int | None
    lockout_reason: str | None
    lockout_until: datetime | None
    lockout_id: str | None  # what an acknowledgement names: the cockpit needs no second call to learn it
    gates: list[GateResult]
    evaluated_at: datetime


def to_risk_status(state: RiskState, profile: RiskProfile) -> RiskStatus:
    return RiskStatus(
        state=state.mode,
        daily_loss_limit_percent=profile.drawdown.daily_loss_limit_percent,
        daily_loss_used_percent=state.daily_loss_used_percent,
        max_drawdown_limit_percent=profile.drawdown.max_drawdown_limit_percent,
        max_drawdown_used_percent=state.max_drawdown_used_percent,
        open_risk_limit_percent=profile.max_open_risk_percent,
        open_risk_percent=state.open_risk_percent,
        correlated_exposure_limit_percent=profile.max_correlated_risk_percent,
        correlated_exposure_percent=state.correlated_exposure_percent,
        max_trades_per_day=profile.max_trades_per_day,
        trades_today=state.trades_today,
        consecutive_losses=state.consecutive_losses,
        lockout_reason=state.lockout_reason,
        lockout_until=state.lockout_until,
        lockout_id=state.lockout_id,
        gates=state.gates,
        evaluated_at=state.evaluated_at,
    )
