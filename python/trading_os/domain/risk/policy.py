"""Per-account risk policy.

``RiskProfile`` composes the sub-policies the mission names — drawdown, news, position limits — next to the
behavioural limits (risk per trade, open risk, correlation, trades per day, consecutive losses). Execution limits
and trading rules live with the account (``domain/accounts``). Which numbers an account gets is decided by its
provider *profile* (``domain/accounts/profiles.py``), never by an ``if provider`` here.

ADR 0015: every value is set by the user, account by account, none is "unlimited". The defaults below only serve
observation; ``configured`` stays False until the user has written their own, and autonomy refuses to start
without it (readiness check ``account_limits_configured``).
"""

from __future__ import annotations

from pydantic import Field

from trading_os.domain.primitives import DomainModel

# Usage fraction of a limit at/above which the posture escalates to "warning".
WARNING_THRESHOLD = 0.6


class DrawdownPolicy(DomainModel):
    daily_loss_limit_percent: float = Field(default=5.0, gt=0)
    max_drawdown_limit_percent: float = Field(default=10.0, gt=0)
    # Balance every percentage is measured against. FTMO: the challenge size, fixed for its whole life. A direct
    # account: the capital the trader commits (Settings). None keeps the historical behaviour (balance at
    # connection time) and must be displayed as "not fixed", never as a floor.
    reference_balance: float | None = Field(
        default=None, ge=1, le=100_000_000
    )  # bounds refuse a typo that disables a gate


class NewsPolicy(DomainModel):
    blackout_minutes: int = Field(default=30, ge=0)  # ± around a whitelisted FRED release
    calendar_max_age_hours: int = Field(default=48, ge=1)  # an older sync counts as unknown → gate closes


class PositionLimits(DomainModel):
    max_open_positions: int = Field(default=3, ge=1)
    max_positions_per_symbol: int = Field(default=1, ge=1)
    max_volume_per_order: float | None = Field(default=None, gt=0)


class RiskProfile(DomainModel):
    max_risk_per_trade_percent: float = Field(default=1.0, gt=0)
    max_open_risk_percent: float = Field(default=2.0, gt=0)
    # Same-currency, same-direction exposure across positions (e.g. long EURUSD + long GBPUSD = short USD twice).
    max_correlated_risk_percent: float = Field(default=1.5, gt=0)
    max_trades_per_day: int = Field(default=6, ge=1)
    max_consecutive_losses: int = Field(default=3, ge=1)
    consecutive_loss_pause_minutes: int = Field(default=30, ge=1)
    drawdown: DrawdownPolicy = DrawdownPolicy()
    news: NewsPolicy = NewsPolicy()
    positions: PositionLimits = PositionLimits()
    configured: bool = False  # True once the user has written the values (autonomy precondition)
