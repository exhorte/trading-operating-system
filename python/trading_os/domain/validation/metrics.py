"""What a list of results says, in R — and how much weight it can bear (ADR 0026). Pure arithmetic: no opinion about profitability."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from trading_os.domain.primitives import DomainModel
from trading_os.domain.validation.simulate import SimulatedTrade

# Below this many trades a result is a description of what happened, not evidence of anything.
MIN_TRADES_FOR_CONCLUSION = 100


class Metrics(DomainModel):
    trades: int
    wins: int
    losses: int
    win_rate: float | None
    expectancy_r: float | None  # mean net R per trade
    total_r: float
    avg_win_r: float | None
    avg_loss_r: float | None
    profit_factor: float | None  # None: no loss yet (a ratio with nothing under it)
    max_drawdown_r: float  # worst peak-to-trough of the cumulative R, in trade order (>= 0)
    longest_losing_streak: int
    enough_trades: bool  # reached MIN_TRADES_FOR_CONCLUSION


def compute_metrics(results: Sequence[float]) -> Metrics:
    wins = [r for r in results if r > 0]
    losses = [r for r in results if r < 0]
    n = len(results)
    peak = 0.0
    total = 0.0
    worst = 0.0
    streak = 0
    longest = 0
    for r in results:
        total += r
        peak = max(peak, total)
        worst = max(worst, peak - total)
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    gross_loss = -sum(losses)
    return Metrics(
        trades=n,
        wins=len(wins),
        losses=len(losses),
        win_rate=len(wins) / n if n else None,
        expectancy_r=total / n if n else None,
        total_r=round(total, 6),
        avg_win_r=sum(wins) / len(wins) if wins else None,
        avg_loss_r=sum(losses) / len(losses) if losses else None,
        profit_factor=sum(wins) / gross_loss if gross_loss > 0 else None,
        max_drawdown_r=round(worst, 6),
        longest_losing_streak=longest,
        enough_trades=n >= MIN_TRADES_FOR_CONCLUSION,
    )


def taken(trades: Sequence[SimulatedTrade]) -> list[SimulatedTrade]:
    """The trades that were really filled, in the order they closed."""
    return sorted((t for t in trades if t.taken and t.closed_at is not None), key=lambda t: t.closed_at)  # type: ignore[arg-type, return-value]


def r_values(trades: Sequence[SimulatedTrade]) -> list[float]:
    return [t.r_net for t in taken(trades) if t.r_net is not None]


def breakdown(trades: Sequence[SimulatedTrade], key: Callable[[SimulatedTrade], str]) -> dict[str, Metrics]:
    """The same metrics per bucket — by trading window, by hour, by weekday."""
    buckets: dict[str, list[float]] = {}
    for trade in taken(trades):
        if trade.r_net is not None:
            buckets.setdefault(key(trade), []).append(trade.r_net)
    return {name: compute_metrics(values) for name, values in sorted(buckets.items())}


def by_window(trade: SimulatedTrade) -> str:
    return trade.window or "outside"


def by_hour_utc(trade: SimulatedTrade) -> str:
    return f"{trade.filled_at.hour:02d}h" if trade.filled_at else "?"


def by_weekday(trade: SimulatedTrade) -> str:
    return trade.filled_at.strftime("%a") if trade.filled_at else "?"
