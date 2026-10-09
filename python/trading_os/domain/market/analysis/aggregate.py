"""Aggregates a lower-timeframe candle series into a higher one (port of ``lib/analysis/aggregate.ts``).

Buckets are aligned to fixed UTC boundaries (epoch-relative), not to wherever the input series happens to start, so the same M1
series always aggregates to the same H1/H4/D1 bars whatever the query window.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from trading_os.domain.market.models import Candle
from trading_os.domain.primitives import Timeframe

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _epoch_ms(moment: datetime) -> int:
    delta = moment.astimezone(UTC) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000 + delta.microseconds // 1000


def _bucket_start_ms(open_ms: int, target_minutes: int) -> int:
    target_ms = target_minutes * 60_000
    return (open_ms // target_ms) * target_ms


def aggregate_candles(
    source: Sequence[Candle], source_timeframe: Timeframe, target_timeframe: Timeframe
) -> list[Candle]:
    """``source`` must be chronological and all on ``source_timeframe``. A bucket is ``closed`` only once it holds every expected
    source candle **and** the last of them is itself closed — a partial or still-forming bucket is still emitted (as the trailing,
    forming bar), consistent with how the live feed always includes one forming bar."""
    if len(source) == 0:
        return []
    target_minutes = target_timeframe.minutes
    expected_members = target_minutes / source_timeframe.minutes

    buckets: list[Candle] = []
    current_bucket_ms = -1
    members = 0

    for candle in source:
        bucket_ms = _bucket_start_ms(_epoch_ms(candle.open_time), target_minutes)

        if bucket_ms != current_bucket_ms:
            current_bucket_ms = bucket_ms
            members = 0
            buckets.append(
                Candle(
                    symbol=candle.symbol, timeframe=target_timeframe,
                    open_time=_EPOCH + timedelta(milliseconds=bucket_ms),
                    open=candle.open, high=candle.high, low=candle.low, close=candle.close,
                    volume=0.0,  # accumulated uniformly below, including this first candle
                    closed=False,
                )
            )  # fmt: skip

        members += 1
        bucket = buckets[-1]
        buckets[-1] = bucket.model_copy(
            update={
                "high": max(bucket.high, candle.high),
                "low": min(bucket.low, candle.low),
                "close": candle.close,
                "volume": bucket.volume + candle.volume,
                "closed": members >= expected_members and candle.closed,
            }
        )

    return buckets
