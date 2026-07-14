"""
One-shot historical candle export (Phase 11 backtesting).

Reads closed M15 bars from the locally running, already-logged-in MT5 terminal
and writes them as JSON Lines. STRICTLY READ-ONLY, no credentials — same
safety posture as mt5_observer.py (zero trade functions imported).

Usage:
    python import_history.py --symbol XAUUSDm --bars 26000 --out candles.jsonl
Then load into TimescaleDB:
    npx tsx scripts/import-candles.ts candles.jsonl
"""

from __future__ import annotations

import argparse
import json

import MetaTrader5 as mt5


def main() -> None:
    parser = argparse.ArgumentParser(description="Export historical M15 candles as JSONL")
    parser.add_argument("--symbol", default="XAUUSDm")
    parser.add_argument("--bars", type=int, default=26_000, help="~1 year of M15")
    parser.add_argument("--out", default="candles.jsonl")
    args = parser.parse_args()

    if not mt5.initialize():
        raise SystemExit(f"[import] mt5.initialize() failed: {mt5.last_error()}")
    if mt5.symbol_info(args.symbol) is None:
        mt5.shutdown()
        raise SystemExit(f"[import] symbol {args.symbol!r} not found in Market Watch")
    mt5.symbol_select(args.symbol, True)

    rates = mt5.copy_rates_from_pos(args.symbol, mt5.TIMEFRAME_M15, 0, args.bars)
    mt5.shutdown()
    if rates is None or len(rates) == 0:
        raise SystemExit("[import] no rates returned — check the symbol / broker history")

    last_index = len(rates) - 1
    with open(args.out, "w", encoding="utf-8") as f:
        for i, r in enumerate(rates):
            f.write(json.dumps({
                "symbol": args.symbol,
                "timeframe": "M15",
                "openTime": int(r["time"]) * 1000,  # epoch ms UTC
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": int(r["tick_volume"]),
                "closed": i != last_index,  # only the newest bar may be forming
            }) + "\n")

    print(f"[import] wrote {len(rates)} candles to {args.out} "
          f"({args.symbol} M15, oldest={rates[0]['time']}, newest={rates[-1]['time']})")


if __name__ == "__main__":
    main()
