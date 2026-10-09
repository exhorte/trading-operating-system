"""ICT/SMC analysis engine — public surface (port of ``lib/analysis``).

Consumes ``Candle`` series and emits the canonical ``MarketContextState``. Pure and transport-agnostic: **context, not signals**
(ADR 0001/0002). Equivalence with the TypeScript original is held by golden vectors generated from it
(``tests/golden/generate_vectors.ts`` → ``tests/golden/analysis.json``).
"""

from __future__ import annotations

from trading_os.domain.market.analysis.aggregate import aggregate_candles
from trading_os.domain.market.analysis.atr import average_true_range
from trading_os.domain.market.analysis.config import DEFAULT_ANALYSIS_CONFIG, AnalysisConfig, ScoreWeights, max_score_of
from trading_os.domain.market.analysis.market_context import analyze_market_context
from trading_os.domain.market.analysis.models import MarketContextState, Swing

__all__ = [
    "DEFAULT_ANALYSIS_CONFIG",
    "AnalysisConfig",
    "MarketContextState",
    "ScoreWeights",
    "Swing",
    "aggregate_candles",
    "analyze_market_context",
    "average_true_range",
    "max_score_of",
]
