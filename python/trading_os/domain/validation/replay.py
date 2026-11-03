"""Replaying a strategy over past candles, one closed M1 candle at a time, exactly as ``StrategyService`` reads them live (ADR 0026).

For each candle inside the trading windows the strategy sees what it would have seen at that close: the last ``m1_bars`` M1 candles
(split into context and reaction), and the higher-timeframe candles that had **closed** by then — never a bar still forming. A setup
re-detected on several consecutive candles is one setup (its identifier), and a setup older than ``act_within`` at the moment it is
seen is counted as stale and never taken, as live. Not replayed: the news calendar and the risk locks of the day (no history).
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta

from pydantic import Field

from trading_os.domain.market.models import Candle
from trading_os.domain.market.sessions import (
    DEFAULT_SESSION_WINDOWS,
    TradingWindow,
    in_trading_window,
    past_ny_lunch,
)
from trading_os.domain.primitives import DomainModel, Timeframe
from trading_os.domain.strategy.s01.config import S01Config
from trading_os.domain.strategy.s01.models import ProposedOutcome, SetupProposal
from trading_os.domain.strategy.s01.proposal import SetupProposalInput, Variant, evaluate_setup
from trading_os.domain.validation.simulate import TradeCosts, TradeSpec


class CandleSet(DomainModel):
    """Closed candles of one symbol, oldest first, per timeframe."""

    m1: list[Candle]
    h1: list[Candle]
    h4: list[Candle]
    d1: list[Candle]
    m15: list[Candle] = Field(default_factory=list)  # the map a variant may read (S02); empty for S01


class ReplayedProposal(DomainModel):
    proposal: SetupProposal
    spec: TradeSpec


class ReplayResult(DomainModel):
    evaluated: int
    skipped_outside_windows: int
    stage_counts: dict[str, int]
    proposals: list[ReplayedProposal]
    stale: int  # seen too late to be acted on, as live


def _closes(candles: Sequence[Candle], timeframe: Timeframe) -> list[datetime]:
    return [c.open_time + timedelta(minutes=timeframe.minutes) for c in candles]


def replay(
    candles: CandleSet,
    *,
    symbol: str,
    config: S01Config,
    variant: Variant,
    start: datetime,
    end: datetime,
    costs: TradeCosts,
    cost_threshold: float,
    windows: Sequence[TradingWindow] | None = None,
) -> ReplayResult:
    windows = config.trading_windows if windows is None else windows  # the strategy's own hours, not S01's (ADR 0030)
    m1 = candles.m1
    h1_close, h4_close, d1_close = (
        _closes(candles.h1, Timeframe.H1),
        _closes(candles.h4, Timeframe.H4),
        _closes(candles.d1, Timeframe.D1),
    )
    m15_close = _closes(candles.m15, Timeframe.M15)
    stages: Counter[str] = Counter()
    seen: set[str] = set()
    proposals: list[ReplayedProposal] = []
    evaluated = skipped = stale = 0
    for i, c in enumerate(m1):
        if not (start <= c.open_time < end):
            continue
        if not in_trading_window(c.open_time, windows) or past_ny_lunch(c.open_time):
            skipped += 1
            continue
        closed_at = c.open_time + timedelta(minutes=1)
        window = m1[max(0, i + 1 - config.m1_bars) : i + 1]
        cutoff = max(0, len(window) - config.reaction_window_m1_bars)
        h1 = candles.h1[max(0, bisect_right(h1_close, closed_at) - config.h1_bars) : bisect_right(h1_close, closed_at)]
        h4 = candles.h4[max(0, bisect_right(h4_close, closed_at) - config.h4_bars) : bisect_right(h4_close, closed_at)]
        d1 = candles.d1[max(0, bisect_right(d1_close, closed_at) - config.d1_bars) : bisect_right(d1_close, closed_at)]
        map_candles: list[Candle] = []
        if variant.use_map_timeframe and window[cutoff:]:
            # the 15-minute bars that had closed before the reaction window: what was known before the sweep, never a forming bar
            reaction_start = window[cutoff].open_time
            upto = bisect_right(m15_close, reaction_start)
            map_candles = candles.m15[max(0, upto - config.map_bars) : upto]
        outcome = evaluate_setup(
            SetupProposalInput(
                symbol=symbol, h4_candles=h4, d1_candles=d1, h1_candles=h1, map_candles=map_candles,
                context_candles=window[:cutoff],
                reaction_candles=window[cutoff:], swing_lookback=config.swing_lookback,
                equal_level_tolerance=config.equal_level_tolerance, session_windows=list(DEFAULT_SESSION_WINDOWS),
                atr_period=config.atr_period, min_body_atr_multiple=config.min_body_atr_multiple,
                min_fvg_size=config.min_fvg_size, spread_buffer=config.spread_buffer, spread=costs.spread,
                commission=costs.commission, cost_threshold=cost_threshold, min_risk_reward=config.min_risk_reward,
                level_decimals=config.level_decimals,
            ),
            variant,
        )  # fmt: skip
        evaluated += 1
        if not isinstance(outcome, ProposedOutcome):
            stages[outcome.stage.value] += 1
            continue
        proposal = outcome.proposal
        if proposal.proposal_id in seen:
            continue
        seen.add(proposal.proposal_id)
        if closed_at - proposal.detected_at > config.act_within:
            stale += 1
            continue
        proposals.append(
            ReplayedProposal(
                proposal=proposal,
                spec=TradeSpec(
                    symbol=symbol, side=proposal.side, entry=proposal.entry_price, stop=proposal.stop_loss,
                    target=proposal.take_profit, placed_at=closed_at,
                ),
            )
        )  # fmt: skip
    return ReplayResult(
        evaluated=evaluated, skipped_outside_windows=skipped, stage_counts=dict(sorted(stages.items())),
        proposals=proposals, stale=stale,
    )  # fmt: skip
