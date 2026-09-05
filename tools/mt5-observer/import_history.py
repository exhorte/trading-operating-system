"""
One-shot historical candle export.

Reads closed M15 bars from the locally running, already-logged-in MT5 terminal
and writes them as JSON Lines. STRICTLY READ-ONLY, no credentials — same
safety posture as mt5_observer.py (zero trade functions imported).

Usage:
    python import_history.py --symbol XAUUSDm --bars 26000 --out candles.jsonl
    # exact UTC bounds:
    python import_history.py --symbol XAUUSDm \
        --from 2024-06-01T00:00:00Z --to 2025-06-06T13:30:00Z --out candles.jsonl
Then load into TimescaleDB:
    npx tsx scripts/import-candles.ts candles.jsonl

--from is inclusive, --to is EXCLUSIVE, so the exported set is reproducible
bit-for-bit regardless of when the export runs. --bars mode remains for
dev-dataset style exports.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import MetaTrader5 as mt5


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export historical M15 candles as JSONL")
    parser.add_argument("--symbol", default="XAUUSDm")
    parser.add_argument("--bars", type=int, default=26_000, help="~1 year of M15 (ignored when --from/--to given)")
    parser.add_argument("--from", dest="from_utc", default=None, help="inclusive UTC bound, e.g. 2024-06-01T00:00:00Z")
    parser.add_argument("--to", dest="to_utc", default=None, help="EXCLUSIVE UTC bound, e.g. 2025-06-06T13:30:00Z")
    parser.add_argument("--out", default="candles.jsonl")
    args = parser.parse_args()

    if (args.from_utc is None) != (args.to_utc is None):
        raise SystemExit("[import] --from and --to must be given together")

    if not mt5.initialize():
        raise SystemExit(f"[import] mt5.initialize() failed: {mt5.last_error()}")
    if mt5.symbol_info(args.symbol) is None:
        mt5.shutdown()
        raise SystemExit(f"[import] symbol {args.symbol!r} not found in Market Watch")
    mt5.symbol_select(args.symbol, True)

    if args.from_utc is not None:
        start = parse_utc(args.from_utc)
        end = parse_utc(args.to_utc)
        rates = mt5.copy_rates_range(args.symbol, mt5.TIMEFRAME_M15, start, end)
        mt5.shutdown()
        if rates is None or len(rates) == 0:
            raise SystemExit("[import] no rates returned — check the symbol / broker history depth")
        # copy_rates_range bounds are inclusive; enforce [from, to) exactly so
        # the dataset (and its hash) is identical on every re-export.
        start_s, end_s = int(start.timestamp()), int(end.timestamp())
        rows = [r for r in rates if start_s <= int(r["time"]) < end_s]
        forming_index = -1  # historical range: every bar is closed
    else:
        rates = mt5.copy_rates_from_pos(args.symbol, mt5.TIMEFRAME_M15, 0, args.bars)
        mt5.shutdown()
        if rates is None or len(rates) == 0:
            raise SystemExit("[import] no rates returned — check the symbol / broker history")
        rows = list(rates)
        forming_index = len(rows) - 1  # only the newest bar may be forming

    with open(args.out, "w", encoding="utf-8") as f:
        for i, r in enumerate(rows):
            f.write(json.dumps({
                "symbol": args.symbol,
                "timeframe": "M15",
                "openTime": int(r["time"]) * 1000,  # epoch ms UTC
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": int(r["tick_volume"]),
                "closed": i != forming_index,
            }) + "\n")

    print(f"[import] wrote {len(rows)} candles to {args.out} "
          f"({args.symbol} M15, oldest={rows[0]['time']}, newest={rows[-1]['time']})")


if __name__ == "__main__":
    main()
