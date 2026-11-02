"""S01 step 1 — daily bias from H4 and D1 structure (port of ``lib/setup/bias.ts``).

Pure assembly over the analysis engine's structure detector: BOS/CHoCH is already validated in body close and free of look-ahead
there, so nothing new is detected here — only combined. « Une seule direction autorisée pour la journée » means H4 and D1 must
agree; any disagreement, or either timeframe having no confirmed shift yet, is treated like S01's own « en consolidation, il n'y a
pas de biais, donc pas de trade »: the bias is neutral and the pipeline stops.
"""

from __future__ import annotations

from collections.abc import Sequence

from trading_os.domain.market.analysis.structure import detect_structure_shifts, structural_bias
from trading_os.domain.market.analysis.swings import detect_swings
from trading_os.domain.market.models import Candle
from trading_os.domain.primitives import Bias


def _timeframe_bias(candles: Sequence[Candle], swing_lookback: int) -> Bias:
    swings = detect_swings(candles, swing_lookback)
    return structural_bias(detect_structure_shifts(candles, swings, swing_lookback))


def agreed_bias(first: Sequence[Candle], second: Sequence[Candle], swing_lookback: int) -> Bias:
    """Two timeframes must show the same confirmed direction; anything else is neutral (no trade)."""
    a = _timeframe_bias(first, swing_lookback)
    b = _timeframe_bias(second, swing_lookback)
    return a if a is b and a is not Bias.NEUTRAL else Bias.NEUTRAL


def daily_bias(h4_candles: Sequence[Candle], d1_candles: Sequence[Candle], swing_lookback: int) -> Bias:
    """H4 and D1 must agree on a direction; anything else is neutral (no trade)."""
    return agreed_bias(h4_candles, d1_candles, swing_lookback)
