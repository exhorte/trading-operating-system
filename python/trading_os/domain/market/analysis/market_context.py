"""Orchestrator: run every detector over a candle series and assemble the canonical ``MarketContextState`` — the traceable « why »
snapshot for one symbol (port of ``lib/analysis/market-context.ts``).

Pure and portable. The analysis is computed at the last closed candle; nothing here reads a future bar.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from trading_os.domain.market.analysis.bias import compute_bias, price_location_of
from trading_os.domain.market.analysis.config import DEFAULT_ANALYSIS_CONFIG, AnalysisConfig, max_score_of
from trading_os.domain.market.analysis.liquidity import detect_liquidity
from trading_os.domain.market.analysis.models import AnalysisFeatures, MarketContextState
from trading_os.domain.market.analysis.pd_arrays import detect_fair_value_gaps, detect_order_blocks
from trading_os.domain.market.analysis.scoring import score_context
from trading_os.domain.market.analysis.structure import detect_structure_shifts, structural_bias
from trading_os.domain.market.analysis.swings import detect_swings
from trading_os.domain.market.models import Candle
from trading_os.domain.market.sessions import session_enabled, session_for_timestamp
from trading_os.domain.primitives import Bias, SymbolCode, Timeframe, TradingSession

RECENT_SWEEP_WINDOW = 3  # how many trailing candles count as a « recent » liquidity sweep


def analyze_market_context(
    symbol: SymbolCode, timeframe: Timeframe, candles: Sequence[Candle], config: AnalysisConfig | None = None
) -> MarketContextState:
    """``candles`` are chronological, oldest first, and should be closed ones only."""
    cfg = config or DEFAULT_ANALYSIS_CONFIG

    if len(candles) == 0:
        return MarketContextState(
            symbol=symbol, timeframe=timeframe, bias=Bias.NEUTRAL, session=TradingSession.OFF_SESSION,
            last_structure_shift=None, active_liquidity_levels=[], active_fair_value_gaps=[], active_order_blocks=[],
            score=0.0, max_score=max_score_of(cfg.score_weights), score_breakdown=[],
            computed_at=datetime(1970, 1, 1, tzinfo=UTC),
        )  # fmt: skip

    last_candle = candles[-1]
    current_price = last_candle.close

    swings = detect_swings(candles, cfg.swing_lookback)
    structure_shifts = detect_structure_shifts(candles, swings, cfg.swing_lookback)
    last_structure_shift = structure_shifts[-1] if structure_shifts else None
    bias = compute_bias(structural_bias(structure_shifts))

    liquidity = detect_liquidity(candles, swings, cfg.equal_level_tolerance)
    fair_value_gaps = detect_fair_value_gaps(candles, cfg.min_fvg_size)
    order_blocks = detect_order_blocks(candles, structure_shifts)

    session = session_for_timestamp(last_candle.open_time, cfg.session_windows)
    price_location = price_location_of(current_price, swings)

    recent_from = candles[max(0, len(candles) - RECENT_SWEEP_WINDOW)].open_time
    recently_swept = any(level.swept_at is not None and level.swept_at >= recent_from for level in liquidity)

    features = AnalysisFeatures(
        swings=swings, structure_shifts=structure_shifts, last_structure_shift=last_structure_shift,
        liquidity=liquidity, fair_value_gaps=fair_value_gaps, order_blocks=order_blocks, session=session, bias=bias,
        price_location=price_location, recently_swept=recently_swept,
    )  # fmt: skip
    scored = score_context(features, current_price, session_enabled(session, cfg.session_windows), cfg.score_weights)

    return MarketContextState(
        symbol=symbol, timeframe=timeframe, bias=bias, session=session, last_structure_shift=last_structure_shift,
        active_liquidity_levels=[level for level in liquidity if level.swept_at is None],
        active_fair_value_gaps=[gap for gap in fair_value_gaps if gap.mitigated_at is None],
        active_order_blocks=[block for block in order_blocks if block.mitigated_at is None],
        score=scored.score, max_score=scored.max_score, score_breakdown=scored.breakdown,
        computed_at=last_candle.open_time,
    )  # fmt: skip
