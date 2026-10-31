"""``export-history`` — one-shot export of historical candles from the terminal as JSON Lines, and ``list-symbols`` (the broker
symbols behind a canonical name). Read-only, no credentials.

``--from`` is inclusive, ``--to`` is EXCLUSIVE, so the exported set is reproducible bit for bit whenever the export runs. ``--bars``
exports the last N bars instead (only the newest may still be forming). Load the file with ``import-candles``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from trading_os.cli.terminal import ReadOnlyTerminal
from trading_os.domain.market.models import Candle
from trading_os.domain.primitives import Timeframe
from trading_os.shared.errors import NotFound, ValidationFailed
from trading_os.shared.time import parse_when

parse_utc = parse_when  # (the command line's name for it)


def candle_row(candle: Candle) -> dict[str, Any]:
    """The JSONL shape ``import-candles`` reads: epoch milliseconds, integer tick volume."""
    return {
        "symbol": candle.symbol,
        "timeframe": candle.timeframe.value,
        "openTime": int(candle.open_time.timestamp()) * 1000,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": int(candle.volume),
        "closed": candle.closed,
    }


@dataclass(frozen=True)
class ExportResult:
    written: int
    oldest: datetime | None
    newest: datetime | None
    offset_known: bool


def select_window(candles: Iterable[Candle], start: datetime, end: datetime) -> list[Candle]:
    """Exactly ``[start, end)``: the terminal's own bounds are inclusive on both sides."""
    return [c for c in candles if start <= c.open_time < end]


async def export_history(
    terminal: ReadOnlyTerminal,
    *,
    symbol: str,
    timeframe: Timeframe,
    out: Path,
    bars: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> ExportResult:
    if (start is None) != (end is None):
        raise ValidationFailed("--from and --to must be given together", code="invalid_window")
    if start is not None and end is not None and start >= end:
        raise ValidationFailed("--from must be before --to", code="invalid_window")
    if await terminal.symbol_info(symbol) is None:
        raise NotFound(f"symbol {symbol!r} not found in the terminal", code="symbol_not_found")
    await terminal.select(symbol)
    offset = await terminal.measure_offset(symbol)

    if start is not None and end is not None:
        found = select_window(await terminal.candles_between(symbol, timeframe, start, end), start, end)
        # a historical range: every bar in it is closed, whatever the reader marks
        candles = [c.model_copy(update={"closed": True}) for c in found]
    else:
        candles = await terminal.candles(symbol, timeframe, bars or 26_000)
    if not candles:
        raise NotFound("no rates returned — check the symbol and the broker's history depth", code="no_rates")

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for candle in candles:
            handle.write(json.dumps(candle_row(candle)) + "\n")
    return ExportResult(len(candles), candles[0].open_time, candles[-1].open_time, offset is not None)


# ------------------------------------------------------------------------------------------------------ list-symbols

SYMBOL_FIELDS = (
    "digits", "point", "trade_tick_value", "trade_tick_size", "volume_min", "volume_max", "volume_step", "trade_stops_level",
)  # fmt: skip


async def list_symbols(terminal: ReadOnlyTerminal, canonical: Sequence[str]) -> list[str]:
    """One block of text per broker symbol behind each canonical name — what a symbol registry needs: exact name, digits, point,
    tick value and size, volume bounds, stops level."""
    lines: list[str] = []
    for name in canonical:
        matches = await terminal.symbols_like(name)
        if not matches:
            lines.append(f"# {name}: no matching broker symbol found")
            continue
        for row in matches:
            lines.append(f"# {name} -> {row.get('name')}")
            lines += [f"  {field:<17}= {row.get(field)}" for field in SYMBOL_FIELDS]
            lines.append("")
    return lines
