"""S01 step 5 — displacement and MSS on M1: a candle body must close beyond the last opposite swing, with an accompanying unfilled FVG,
and a body of at least 1.5 x ATR(14) (port of ``lib/setup/displacement.ts``).

« Une mèche qui traverse ne vaut rien » is handled by construction: the break test compares to ``close``, not ``high``/``low``, so a
wick beyond the swing with a close that falls back never qualifies. Only the bars up to the candle under test feed the ATR and the FVG
at that bar — no look-ahead.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from trading_os.domain.market.analysis.atr import average_true_range
from trading_os.domain.market.analysis.models import FairValueGap
from trading_os.domain.market.analysis.pd_arrays import detect_fair_value_gaps
from trading_os.domain.market.models import Candle
from trading_os.domain.primitives import Bias, DomainModel, Side


class DisplacementEvent(DomainModel):
    occurred_at: datetime
    broken_swing_price: float
    fair_value_gap: FairValueGap
    body_size: float
    atr: float


class DisplacementConfig(DomainModel):
    atr_period: int
    min_body_atr_multiple: float
    min_fvg_size: float


def _side_to_bias(side: Side) -> Bias:
    return Bias.BULLISH if side is Side.BUY else Bias.BEARISH


def detect_displacement(
    candles: Sequence[Candle], side: Side, opposite_swing_price: float, config: DisplacementConfig
) -> DisplacementEvent | None:
    """``candles`` is the entry-timeframe series from the sweep onward. Returns the first qualifying candle, or ``None``."""
    for i in range(2, len(candles)):
        c = candles[i]
        broke_body = c.close > opposite_swing_price if side is Side.BUY else c.close < opposite_swing_price
        if not broke_body:
            continue

        body_size = abs(c.close - c.open)
        atr = average_true_range(candles[: i + 1], config.atr_period)
        if atr <= 0 or body_size < config.min_body_atr_multiple * atr:
            continue  # body too small relative to volatility -> not a real displacement

        gaps = detect_fair_value_gaps(candles[: i + 1], config.min_fvg_size)
        gap = next(
            (
                g
                for g in gaps
                if g.detected_at == c.open_time and g.direction is _side_to_bias(side) and g.mitigated_at is None
            ),
            None,
        )
        if gap is None:
            continue  # no accompanying unfilled FVG on this candle

        return DisplacementEvent(
            occurred_at=c.open_time, broken_swing_price=opposite_swing_price, fair_value_gap=gap, body_size=body_size,
            atr=atr,
        )  # fmt: skip
    return None
