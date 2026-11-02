"""Rolling windows over a frozen configuration (ADR 0026): does the result hold from one stretch of time to the next?

Nothing is fitted in one window and tested in the next — the rules never change. This only cuts the period into successive pieces and
measures each one, so a result carried by a single lucky fortnight shows as such.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from pydantic import Field

from trading_os.domain.primitives import DomainModel
from trading_os.domain.validation.metrics import Metrics, compute_metrics, taken
from trading_os.domain.validation.simulate import SimulatedTrade


class WindowResult(DomainModel):
    start: datetime
    end: datetime
    metrics: Metrics


class StabilitySummary(DomainModel):
    windows: list[WindowResult]
    windows_with_trades: int
    windows_positive: int  # expectancy above zero
    share_positive: float | None  # None: no window had a trade


class WalkForwardSettings(DomainModel):
    window_days: int = Field(default=14, ge=1)
    step_days: int = Field(default=7, ge=1)


def rolling_windows(
    trades: Sequence[SimulatedTrade], start: datetime, end: datetime, settings: WalkForwardSettings
) -> StabilitySummary:
    window = timedelta(days=settings.window_days)
    step = timedelta(days=settings.step_days)
    done = taken(trades)
    results: list[WindowResult] = []
    cursor = start
    while cursor + window <= end:
        inside = [t.r_net for t in done if t.closed_at is not None and cursor <= t.closed_at < cursor + window]
        results.append(
            WindowResult(
                start=cursor, end=cursor + window, metrics=compute_metrics([r for r in inside if r is not None])
            )
        )
        cursor += step
    with_trades = [w for w in results if w.metrics.trades > 0]
    positive = [w for w in with_trades if (w.metrics.expectancy_r or 0.0) > 0]
    return StabilitySummary(
        windows=results, windows_with_trades=len(with_trades), windows_positive=len(positive),
        share_positive=len(positive) / len(with_trades) if with_trades else None,
    )  # fmt: skip
