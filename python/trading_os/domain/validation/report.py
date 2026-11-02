"""One validation run, end to end, and what it must say about itself (ADR 0026): the configuration's fingerprint, what was assumed, what was
not modelled, how many times these data have been looked at before, and how much the number of trades can bear.

``run_validation`` is pure: candles in, report out. The ledger of past looks is read and written by the command, not here.
"""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from pydantic import Field

from trading_os.domain.market.sessions import NY_TIME_ZONE
from trading_os.domain.primitives import DomainModel
from trading_os.domain.strategy.s01.config import S01Config
from trading_os.domain.strategy.s01.proposal import Variant
from trading_os.domain.validation.metrics import (
    MIN_TRADES_FOR_CONCLUSION,
    Metrics,
    breakdown,
    by_hour_utc,
    by_weekday,
    by_window,
    compute_metrics,
    r_values,
    taken,
)
from trading_os.domain.validation.montecarlo import MonteCarloResult, MonteCarloSettings, monte_carlo
from trading_os.domain.validation.replay import CandleSet, replay
from trading_os.domain.validation.simulate import SimulatedTrade, SimulationSettings, TradeCosts, simulate_trade
from trading_os.domain.validation.walkforward import StabilitySummary, WalkForwardSettings, rolling_windows

ASSUMPTIONS = (
    "every proposal that reached the order stage is taken: the open-risk, correlation and trades-per-day limits are not applied",
    "the spread and the commission are the constant values given, not the history of the day",
    "candles are bid prices; a limit buy fills when the ask (bid + spread) reaches it, a limit sell when the bid does",
    "in one candle the stop is checked before the target; on the candle that fills the order, only the stop can fire",
)
NOT_MODELLED = (
    "the news calendar (no history of the releases)",
    "the risk locks of the day (loss limits, consecutive-loss pause)",
    "partial fills, requotes, swaps and gaps over a closed market",
)


class RunSettings(DomainModel):
    strategy_id: str
    strategy_version: str
    symbol: str
    start: datetime
    end: datetime
    config: S01Config
    costs: TradeCosts
    cost_threshold: float = 0.25
    simulation: SimulationSettings = Field(default_factory=SimulationSettings)
    monte_carlo: MonteCarloSettings
    walk_forward: WalkForwardSettings = Field(default_factory=WalkForwardSettings)


class OrderCounts(DomainModel):
    filled: int
    unfilled: int
    expired: int
    invalidated: int


class ValidationReport(DomainModel):
    strategy_id: str
    strategy_version: str
    symbol: str
    period_start: datetime
    period_end: datetime
    fingerprint: str
    generated_at: datetime
    assumptions: list[str]
    not_modelled: list[str]
    evaluated_candles: int
    skipped_outside_windows: int
    stage_counts: dict[str, int]
    proposals: int
    stale_proposals: int
    orders: OrderCounts
    outcomes: dict[str, int]
    metrics: Metrics
    by_window: dict[str, Metrics]
    by_hour: dict[str, Metrics]
    by_weekday: dict[str, Metrics]
    stability: StabilitySummary
    monte_carlo: MonteCarloResult | None
    previous_looks: int = 0
    warnings: list[str] = Field(default_factory=list)


def fingerprint(settings: RunSettings) -> str:
    """Identifies the configuration, not the period: two runs with the same rules share it, whatever data they read."""
    frozen = {
        "strategy": [settings.strategy_id, settings.strategy_version],
        "symbol": settings.symbol,
        "config": settings.config.model_dump(mode="json"),
        "costs": settings.costs.model_dump(mode="json"),
        "cost_threshold": settings.cost_threshold,
        "simulation": settings.simulation.model_dump(mode="json"),
        "risk_percent": settings.monte_carlo.risk_percent,
    }
    return hashlib.sha256(json.dumps(frozen, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def previous_looks(ledger: Sequence[Mapping[str, object]], settings: RunSettings) -> int:
    """How many earlier runs, with any configuration, read a period that overlaps this one."""
    count = 0
    for entry in ledger:
        if entry.get("symbol") != settings.symbol:
            continue
        start = datetime.fromisoformat(str(entry["period_start"]))
        end = datetime.fromisoformat(str(entry["period_end"]))
        if start < settings.end and end > settings.start:
            count += 1
    return count


def ledger_entry(report: ValidationReport) -> dict[str, object]:
    return {
        "at": report.generated_at.isoformat(),
        "strategy": report.strategy_id,
        "symbol": report.symbol,
        "fingerprint": report.fingerprint,
        "period_start": report.period_start.isoformat(),
        "period_end": report.period_end.isoformat(),
        "trades": report.metrics.trades,
    }


def _trading_day(trade: SimulatedTrade) -> str:
    assert trade.closed_at is not None
    return trade.closed_at.astimezone(NY_TIME_ZONE).date().isoformat()


def run_validation(
    candles: CandleSet,
    settings: RunSettings,
    variant: Variant,
    *,
    now: datetime,
    ledger: Sequence[Mapping[str, object]] = (),
) -> ValidationReport:
    result = replay(
        candles, symbol=settings.symbol, config=settings.config, variant=variant, start=settings.start, end=settings.end,
        costs=settings.costs, cost_threshold=settings.cost_threshold,
    )  # fmt: skip
    m1_times = [c.open_time for c in candles.m1]
    trades: list[SimulatedTrade] = []
    for proposed in result.proposals:
        first = bisect_left(m1_times, proposed.spec.placed_at)
        trades.append(
            simulate_trade(
                proposed.spec, candles.m1[first:], settings.costs, settings.simulation, settings.config.trading_windows
            )
        )  # the window of the order is read against the strategy's own hours (ADR 0030)

    done = taken(trades)
    outcomes = Counter(t.outcome for t in trades)
    metrics = compute_metrics(r_values(trades))
    days: dict[str, list[float]] = {}
    for trade in done:
        if trade.r_net is not None:
            days.setdefault(_trading_day(trade), []).append(trade.r_net)
    warnings: list[str] = []
    if not metrics.enough_trades:
        warnings.append(
            f"{metrics.trades} trade(s): below the {MIN_TRADES_FOR_CONCLUSION} needed before a result means anything — "
            "this describes what happened on this sample, it does not show an edge"
        )
    looks = previous_looks(ledger, settings)
    if looks:
        warnings.append(
            f"these data were already read by {looks} earlier run(s): the more they are read, the less a good result is worth"
        )
    if not days:
        warnings.append("no trade was filled: the distribution below is empty")
    return ValidationReport(
        strategy_id=settings.strategy_id, strategy_version=settings.strategy_version, symbol=settings.symbol,
        period_start=settings.start, period_end=settings.end, fingerprint=fingerprint(settings), generated_at=now,
        assumptions=list(ASSUMPTIONS), not_modelled=list(NOT_MODELLED), evaluated_candles=result.evaluated,
        skipped_outside_windows=result.skipped_outside_windows, stage_counts=result.stage_counts,
        proposals=len(result.proposals), stale_proposals=result.stale,
        orders=OrderCounts(
            filled=len(done), unfilled=outcomes["unfilled"], expired=outcomes["expired"], invalidated=outcomes["invalidated"]
        ),
        outcomes=dict(sorted(outcomes.items())), metrics=metrics, by_window=breakdown(trades, by_window),
        by_hour=breakdown(trades, by_hour_utc), by_weekday=breakdown(trades, by_weekday),
        stability=rolling_windows(trades, settings.start, settings.end + timedelta(seconds=1), settings.walk_forward),
        monte_carlo=monte_carlo(list(days.values()), settings.monte_carlo), previous_looks=looks, warnings=warnings,
    )  # fmt: skip
