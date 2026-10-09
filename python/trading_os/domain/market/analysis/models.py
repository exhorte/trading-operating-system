"""ICT/SMC analysis models: liquidity, PD arrays, structure, market context (port of ``lib/domain/analysis.ts`` and
``lib/analysis/types.ts``).

These are the structured facts the analysis engine emits so that every decision stays traceable to market context. They give
**context, not signals**: nothing here says what to trade (ADR 0001/0002).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from trading_os.domain.primitives import Bias, DomainModel, SymbolCode, Timeframe, TradingSession

PriceLocation = Literal["premium", "equilibrium", "discount"]


class LiquidityKind(StrEnum):
    BUY_SIDE = "buy_side"
    SELL_SIDE = "sell_side"
    EQUAL_HIGHS = "equal_highs"
    EQUAL_LOWS = "equal_lows"
    SESSION_HIGH = "session_high"
    SESSION_LOW = "session_low"
    PREVIOUS_DAY_HIGH = "previous_day_high"
    PREVIOUS_DAY_LOW = "previous_day_low"


class StructureShiftKind(StrEnum):
    BREAK_OF_STRUCTURE = "break_of_structure"
    CHANGE_OF_CHARACTER = "change_of_character"
    LIQUIDITY_SWEEP_REVERSAL = "liquidity_sweep_reversal"


class Swing(DomainModel):
    """A confirmed fractal pivot. ``index`` refers to the source candle array."""

    kind: Literal["high", "low"]
    price: float
    index: int
    time: datetime


class LiquidityLevel(DomainModel):
    """A resting-liquidity level the market may draw toward or sweep."""

    level_id: str
    symbol: SymbolCode
    timeframe: Timeframe
    kind: LiquidityKind
    price: float
    swept_at: datetime | None  # None while the level is intact
    detected_at: datetime


class FairValueGap(DomainModel):
    """Imbalance between the first and the third candle of a three-candle sequence."""

    fvg_id: str
    symbol: SymbolCode
    timeframe: Timeframe
    direction: Bias
    high: float
    low: float
    filled_percent: float  # 0-100
    mitigated_at: datetime | None  # None while the gap remains unmitigated
    detected_at: datetime


class OrderBlock(DomainModel):
    """The last opposing candle range before a displacement move."""

    order_block_id: str
    symbol: SymbolCode
    timeframe: Timeframe
    direction: Bias
    high: float
    low: float
    mitigated_at: datetime | None  # None while price has not returned to the block
    detected_at: datetime


class StructureShift(DomainModel):
    """A confirmed market-structure event on one timeframe."""

    shift_id: str
    symbol: SymbolCode
    timeframe: Timeframe
    kind: StructureShiftKind
    direction: Bias
    broken_level: float  # the price whose break confirmed the shift
    occurred_at: datetime


class ScoreComponent(DomainModel):
    label: str
    score: float
    max_score: float


class MarketContextState(DomainModel):
    """Aggregated analysis state for one symbol: the « why » snapshot, with the referenced entities embedded so a stored context
    stays replayable without joins."""

    symbol: SymbolCode
    timeframe: Timeframe
    bias: Bias
    session: TradingSession
    last_structure_shift: StructureShift | None
    active_liquidity_levels: list[LiquidityLevel]
    active_fair_value_gaps: list[FairValueGap]
    active_order_blocks: list[OrderBlock]
    score: float
    max_score: float
    score_breakdown: list[ScoreComponent]
    computed_at: datetime


class AnalysisFeatures(DomainModel):
    """The detectors' output, consumed by the bias and scoring stages before the final state is assembled."""

    swings: list[Swing]
    structure_shifts: list[StructureShift]
    last_structure_shift: StructureShift | None
    liquidity: list[LiquidityLevel]
    fair_value_gaps: list[FairValueGap]
    order_blocks: list[OrderBlock]
    session: TradingSession
    bias: Bias
    price_location: PriceLocation
    recently_swept: bool  # a liquidity level was swept by the most recent candles
