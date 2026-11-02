"""Monte Carlo by blocks of days (ADR 0026): draw, with replacement, whole trading days that really happened, and see how often the
account would have crossed its limits. A day keeps its trades together, so a bad morning stays a bad morning.

A distribution over a sample from the past — not a forecast. Fixed seed, so the same data gives the same answer.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from pydantic import Field

from trading_os.domain.primitives import DomainModel


class MonteCarloResult(DomainModel):
    paths: int
    horizon_days: int
    risk_percent: float
    seed: int
    days_sampled: int  # distinct days the draw came from
    p_daily_breach: float  # share of paths where some day lost the daily limit
    p_total_breach: float  # share of paths where the equity fell to the total limit
    return_p05: float  # percent of the initial capital at the end of the horizon
    return_p50: float
    return_p95: float
    max_drawdown_p50: float  # percent, worst peak-to-trough within a path
    max_drawdown_p95: float


class MonteCarloSettings(DomainModel):
    risk_percent: float = Field(gt=0, le=10)  # percent of the initial capital risked per trade (R)
    daily_limit_percent: float = Field(default=5.0, gt=0)
    total_limit_percent: float = Field(default=10.0, gt=0)
    paths: int = Field(default=5000, ge=100, le=200_000)
    horizon_days: int = Field(default=20, ge=1, le=260)
    seed: int = 1


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[index]


def monte_carlo(days: Sequence[Sequence[float]], settings: MonteCarloSettings) -> MonteCarloResult | None:
    """``days``: the net R of every trade of each trading day, in order. ``None`` when there is no day to draw from."""
    pool = [list(day) for day in days if day]
    if not pool:
        return None
    rng = random.Random(settings.seed)
    risk = settings.risk_percent
    daily_breaches = 0
    total_breaches = 0
    finals: list[float] = []
    drawdowns: list[float] = []
    for _ in range(settings.paths):
        equity = 0.0  # percent of the initial capital, static (prop-firm convention)
        peak = 0.0
        worst = 0.0
        daily_hit = False
        total_hit = False
        for _day in range(settings.horizon_days):
            day = pool[rng.randrange(len(pool))]
            running = 0.0
            for r in day:
                running += r * risk
                if running <= -settings.daily_limit_percent:
                    daily_hit = True
                level = equity + running
                peak = max(peak, level)
                worst = max(worst, peak - level)
                if level <= -settings.total_limit_percent:
                    total_hit = True
            equity += running
            if total_hit:
                break
        daily_breaches += daily_hit
        total_breaches += total_hit
        finals.append(equity)
        drawdowns.append(worst)
    finals.sort()
    drawdowns.sort()
    n = settings.paths
    return MonteCarloResult(
        paths=n, horizon_days=settings.horizon_days, risk_percent=risk, seed=settings.seed, days_sampled=len(pool),
        p_daily_breach=daily_breaches / n, p_total_breach=total_breaches / n,
        return_p05=round(_quantile(finals, 0.05), 4), return_p50=round(_quantile(finals, 0.5), 4),
        return_p95=round(_quantile(finals, 0.95), 4),
        max_drawdown_p50=round(_quantile(drawdowns, 0.5), 4), max_drawdown_p95=round(_quantile(drawdowns, 0.95), 4),
    )  # fmt: skip
