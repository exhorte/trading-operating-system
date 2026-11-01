"""Risk-state evaluator: run every gate over the current account and derive the posture
(normal / warning / locked) and the lockout reason.

Hard lockouts are account-level breaches (daily loss, drawdown, max trades, consecutive losses) that stop all
trading; the other gates (open risk, correlation, positions, spread, session, news, connection) block *new
entries* without locking the account. Port of ``lib/risk/evaluate.ts`` — same ids, same labels, same rounding.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from trading_os.domain.market.calendar import UpcomingRelease
from trading_os.domain.primitives import AccountId, DomainModel
from trading_os.domain.risk.dynamic_risk import (
    RemainingBudget,
    RiskAllowance,
    performance_percent,
    resolve_risk_allowance,
)
from trading_os.domain.risk.gates import (
    connection_gate,
    consecutive_loss_gate,
    correlation_gate,
    daily_loss_gate,
    max_drawdown_gate,
    max_trades_gate,
    news_gate,
    open_risk_gate,
    performance_stop_gate,
    position_limit_gate,
    session_gate,
    spread_gate,
    weekly_loss_gate,
)
from trading_os.domain.risk.policy import WARNING_THRESHOLD, RiskProfile
from trading_os.domain.risk.state import RiskMode, RiskState, round_half_up


class RiskInputs(DomainModel):
    """Everything the evaluator needs, pre-computed by the caller. ``None`` means *unknown*, never zero-as-fact."""

    account_id: AccountId
    now: datetime
    profile: RiskProfile
    initial_balance: float  # denominator of the percent limits (the reference balance)
    # False = no initial capital recorded: ``initial_balance`` is only today's balance standing in for it. The percent
    # limits still read it, but the performance grid does not (ADR 0019): fail closed, entries refused.
    reference_fixed: bool = False
    day_start_equity: float
    week_start_equity: float
    equity: float
    balance: float
    open_risk_percent: float = 0.0
    unprotected_positions: tuple[str, ...] = ()
    unmeasured_positions: tuple[str, ...] = ()
    correlated_exposure_percent: float = 0.0
    correlated_key: tuple[str, str] | None = None
    open_positions: int = 0
    trades_today: int | None = None
    consecutive_losses: int | None = None
    spread: float | None = None  # price units
    spread_cap: float | None = None  # optional user ceiling for the symbol, price units
    require_tick: bool = False  # True when an order is being reviewed
    agent_connected: bool = False
    in_trading_window: bool = False
    window_label: str | None = None
    # None = calendar unknown or stale → the news gate fails closed.
    calendar: tuple[UpcomingRelease, ...] | None = Field(default=None)


def loss_percent(start_equity: float, equity: float, reference: float) -> float:
    """Loss since ``start_equity``, in percent of the reference balance (never negative), unrounded."""
    denominator = reference if reference > 0 else 1.0
    return max(0.0, (start_equity - equity) / denominator * 100)


def risk_allowance(inputs: RiskInputs) -> RiskAllowance:
    """What one new trade may risk (ADR 0019): the grid, the 200 $ trigger, the profile ceiling and the loss budgets
    that are left. The budgets use the unrounded usage — a rounded 4.96 % must not buy 0.04 % more than there is."""
    profile = inputs.profile
    limits = profile.drawdown
    reference = inputs.initial_balance
    open_risk = inputs.open_risk_percent
    budgets = [
        RemainingBudget(
            code="daily_budget",
            label="daily loss",
            limit_percent=limits.daily_loss_limit_percent,
            used_percent=loss_percent(inputs.day_start_equity, inputs.equity, reference),
            open_risk_percent=open_risk,
        ),
        RemainingBudget(
            code="weekly_budget",
            label="weekly loss",
            limit_percent=limits.weekly_loss_limit_percent,
            used_percent=loss_percent(inputs.week_start_equity, inputs.equity, reference),
            open_risk_percent=open_risk,
        ),
        RemainingBudget(
            code="overall_budget",
            label="total loss",
            limit_percent=limits.max_drawdown_limit_percent,
            used_percent=loss_percent(reference, inputs.equity, reference),
            open_risk_percent=open_risk,
        ),
    ]
    return resolve_risk_allowance(
        profile.dynamic,
        initial_capital=reference if inputs.reference_fixed else None,
        equity=inputs.equity,
        per_trade_ceiling_percent=profile.max_risk_per_trade_percent,
        budgets=budgets,
    )


def evaluate_risk_state(inputs: RiskInputs) -> RiskState:
    profile = inputs.profile
    denominator = inputs.initial_balance if inputs.initial_balance > 0 else 1.0
    daily_used = round_half_up(loss_percent(inputs.day_start_equity, inputs.equity, denominator), 1)
    weekly_used = round_half_up(loss_percent(inputs.week_start_equity, inputs.equity, denominator), 1)
    drawdown_used = round_half_up(loss_percent(inputs.initial_balance, inputs.equity, denominator), 1)
    performance = (
        performance_percent(inputs.initial_balance, inputs.equity)
        if inputs.reference_fixed and inputs.initial_balance > 0 and inputs.equity > 0
        else None
    )

    daily = daily_loss_gate(daily_used, profile.drawdown)
    weekly = weekly_loss_gate(weekly_used, profile.drawdown)
    performance_stop = performance_stop_gate(performance, profile.dynamic.stop_level_percent)
    drawdown = max_drawdown_gate(drawdown_used, profile.drawdown)
    trades = max_trades_gate(inputs.trades_today, profile)
    consecutive = consecutive_loss_gate(inputs.consecutive_losses, profile)
    gates = [
        daily,
        weekly,
        performance_stop,
        drawdown,
        open_risk_gate(
            inputs.open_risk_percent,
            profile.max_open_risk_percent,
            unprotected=inputs.unprotected_positions,
            unknown_spec=inputs.unmeasured_positions,
        ),
        correlation_gate(
            inputs.correlated_exposure_percent, profile.max_correlated_risk_percent, inputs.correlated_key
        ),
        trades,
        consecutive,
        position_limit_gate(inputs.open_positions, profile.positions),
        spread_gate(inputs.spread, inputs.spread_cap, require_tick=inputs.require_tick),
        session_gate(inputs.in_trading_window, inputs.window_label),
        news_gate(inputs.calendar, inputs.now, profile.news),
        connection_gate(inputs.agent_connected),
    ]

    hard_breaches = [gate for gate in (daily, weekly, performance_stop, drawdown, trades, consecutive) if gate.blocked]
    locked = bool(hard_breaches)
    limits = profile.drawdown
    warning = not locked and (
        daily_used >= limits.daily_loss_limit_percent * WARNING_THRESHOLD
        or weekly_used >= limits.weekly_loss_limit_percent * WARNING_THRESHOLD
        or drawdown_used >= limits.max_drawdown_limit_percent * WARNING_THRESHOLD
        or inputs.open_risk_percent >= profile.max_open_risk_percent * WARNING_THRESHOLD
    )
    mode = RiskMode.LOCKED if locked else RiskMode.WARNING if warning else RiskMode.NORMAL

    return RiskState(
        account_id=inputs.account_id,
        mode=mode,
        daily_loss_used_percent=daily_used,
        weekly_loss_used_percent=weekly_used,
        max_drawdown_used_percent=drawdown_used,
        performance_percent=None if performance is None else round(performance, 4),
        allowance=risk_allowance(inputs),
        open_risk_percent=inputs.open_risk_percent,
        correlated_exposure_percent=inputs.correlated_exposure_percent,
        trades_today=inputs.trades_today,
        consecutive_losses=inputs.consecutive_losses,
        lockout_reason="; ".join(gate.label for gate in hard_breaches) if locked else None,
        lockout_until=None,
        gates=gates,
        evaluated_at=inputs.now,
    )
