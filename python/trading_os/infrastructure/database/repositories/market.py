"""Market data: candles and ticks (Timescale hypertables when available) and the news calendar cache."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from trading_os.domain.market.calendar import UpcomingRelease
from trading_os.domain.market.models import Candle, Tick
from trading_os.domain.primitives import Timeframe
from trading_os.infrastructure.database.pool import Database, Row


def _to_candle(row: Row) -> Candle:
    return Candle(
        symbol=row["symbol"],
        timeframe=Timeframe(row["timeframe"]),
        open_time=row["open_time"],
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=row["volume"],
        closed=row["closed"],
    )


class MarketRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert_candles(self, candles: Sequence[Candle]) -> None:
        await self._db.execute_many(
            "INSERT INTO candles (symbol, timeframe, open_time, open, high, low, close, volume, closed) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (symbol, timeframe, open_time) DO UPDATE SET open = EXCLUDED.open, high = EXCLUDED.high, "
            "low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume, closed = EXCLUDED.closed",
            [
                (c.symbol, c.timeframe.value, c.open_time, c.open, c.high, c.low, c.close, c.volume, c.closed)
                for c in candles
            ],
        )

    async def candles(self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> list[Candle]:
        rows = await self._db.fetch_all(
            "SELECT symbol, timeframe, open_time, open, high, low, close, volume, closed FROM candles "
            "WHERE symbol = %s AND timeframe = %s AND open_time >= %s AND open_time <= %s ORDER BY open_time ASC",
            (symbol, timeframe.value, start, end),
        )
        return [_to_candle(r) for r in rows]

    async def last_candle_time(self, symbol: str, timeframe: Timeframe) -> datetime | None:
        value = await self._db.fetch_value(
            "SELECT max(open_time) FROM candles WHERE symbol = %s AND timeframe = %s", (symbol, timeframe.value)
        )
        return value  # type: ignore[no-any-return]

    async def insert_ticks(self, ticks: Sequence[Tick]) -> None:
        await self._db.execute_many(
            "INSERT INTO ticks (symbol, ts, bid, ask) VALUES (%s, %s, %s, %s)",
            [(t.symbol, t.time, t.bid, t.ask) for t in ticks],
        )

    async def spread_by_hour(self, symbol: str, start: datetime, end: datetime) -> list[Row]:
        """Average and maximum spread per hour of the day (UTC) — the measurement behind the cost gate (ADR 0015)."""
        return await self._db.fetch_all(
            "SELECT extract(hour FROM ts)::int AS hour, count(*) AS ticks, avg(ask - bid) AS avg_spread, "
            "max(ask - bid) AS max_spread FROM ticks WHERE symbol = %s AND ts >= %s AND ts < %s "
            "GROUP BY 1 ORDER BY 1",
            (symbol, start, end),
        )


class NewsRepository:
    """FRED release calendar cache. Reference data, not a business event: a refresh replaces a release's *future* rows
    at once. It must survive a restart with no network — the news gate fails closed on an empty or stale cache."""

    SYNC_KEY = "news.synced_at"

    def __init__(self, db: Database) -> None:
        self._db = db

    async def upcoming(self, now: datetime) -> list[UpcomingRelease] | None:
        """``None`` = the calendar was never synced (unknown, not empty)."""
        ever = await self._db.fetch_value("SELECT EXISTS(SELECT 1 FROM news_releases)")
        if not ever:
            return None
        rows = await self._db.fetch_all(
            "SELECT release_id, label, scheduled_at FROM news_releases WHERE scheduled_at > %s "
            "ORDER BY scheduled_at ASC",
            (now,),
        )
        return [UpcomingRelease.model_validate(dict(r)) for r in rows]

    async def around(self, now: datetime, lookback: timedelta) -> list[UpcomingRelease] | None:
        """Releases from ``lookback`` ago onward — the news blackout is symmetric, so a release that has just passed
        still counts for a while. ``None`` = never synced."""
        ever = await self._db.fetch_value("SELECT EXISTS(SELECT 1 FROM news_releases)")
        if not ever:
            return None
        rows = await self._db.fetch_all(
            "SELECT release_id, label, scheduled_at FROM news_releases WHERE scheduled_at > %s "
            "ORDER BY scheduled_at ASC",
            (now - lookback,),
        )
        return [UpcomingRelease.model_validate(dict(r)) for r in rows]

    async def replace_upcoming(self, release_id: int, label: str, scheduled: Sequence[datetime], now: datetime) -> None:
        async with self._db.transaction() as conn:
            await conn.execute(
                "DELETE FROM news_releases WHERE release_id = %s AND scheduled_at >= %s", (release_id, now)
            )
            for at in scheduled:
                await conn.execute(
                    "INSERT INTO news_releases (release_id, label, scheduled_at) VALUES (%s, %s, %s) "
                    "ON CONFLICT (release_id, scheduled_at) DO NOTHING",
                    (release_id, label, at),
                )
