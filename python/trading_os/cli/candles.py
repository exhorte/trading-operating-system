"""``import-candles`` — bulk-load historical candles (JSON Lines, as ``export-history`` writes them) into the ``candles`` table
Idempotent: an upsert on ``(symbol, timeframe, open_time)``, safe to re-run."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_os.domain.market.models import Candle
from trading_os.domain.primitives import Timeframe
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.shared.errors import ValidationFailed

BATCH = 1_000


def parse_candle(line: str, number: int) -> Candle:
    """One JSONL line → a candle. A line that cannot be read stops the import, naming its number — a half-read file is not loaded
    silently."""
    try:
        row: dict[str, Any] = json.loads(line)
        return Candle(
            symbol=str(row["symbol"]),
            timeframe=Timeframe(row["timeframe"]),
            open_time=datetime.fromtimestamp(int(row["openTime"]) / 1000, UTC),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            closed=bool(row["closed"]),
        )
    except (ValueError, KeyError, TypeError) as error:
        raise ValidationFailed(
            f"line {number}: not a candle ({type(error).__name__})", code="invalid_candle_line"
        ) from error


def read_candles(path: Path) -> Iterator[Candle]:
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if line.strip():
                yield parse_candle(line, number)


async def import_candles(repos: Repositories, path: Path) -> int:
    """Upsert every candle of ``path``; returns how many were read."""
    total = 0
    batch: list[Candle] = []
    for candle in read_candles(path):
        batch.append(candle)
        if len(batch) >= BATCH:
            await repos.market.upsert_candles(batch)
            total += len(batch)
            batch = []
    if batch:
        await repos.market.upsert_candles(batch)
        total += len(batch)
    return total
