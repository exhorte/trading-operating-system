"""
Periodic candle export for EA-02 — EURUSD, read-only (GBPUSD set aside on
2026-09-25; XAUUSD is outside S01's scope until its thresholds are
ATR-relative — S01 fiche).

Despite the file name (kept: it is the documented entry point in the runbook
and EA-02's fiche), this exports M1 *and* the higher timeframes S01 needs —
H1, H4, D1 — each pulled natively from MT5, never aggregated. See HTF_BARS
for why aggregating them from the M1 window silently broke step 1 of S01.

Part of the architecture in
context/product/tools/EA-02-observe-taux-accord.md: this process only
talks to MT5 and writes local JSONL; scripts/run-setup-detection.ts (a
separate Node process) reads that JSONL, upserts it into TimescaleDB, and
runs the S01 detection. mt5_observer.py is NOT touched — this is a fully
separate process, same posture as log_spread.py in Phase 0.

Every `--interval` seconds, re-fetches the last `--bars` M1 candles (plus
HTF_BARS of each higher timeframe) per symbol and OVERWRITES one JSONL file
per symbol and timeframe (a bounded, current snapshot — not an ever-growing
append log): m1_eurusd.jsonl, h1_eurusd.jsonl, h4_eurusd.jsonl, ...

Usage (Windows, terminal open and logged into the demo account). The
out-dir must be the directory the worker reads, i.e. TRADINGOS_CANDLES_DIR,
which defaults to this one — passing `--out-dir .` from the repo root
instead writes a second copy nothing reads, while the worker keeps
evaluating a frozen snapshot:
    python tools/mt5-observer/export_m1_candles.py \
        --symbols EURUSD --out-dir tools/mt5-observer
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import MetaTrader5 as mt5

DEFAULT_BARS = 1500  # ~25h of M1 — the sweep/displacement window, nothing more
DEFAULT_INTERVAL_SECONDS = 30

# Higher timeframes are pulled NATIVELY from MT5 rather than aggregated from
# the M1 window above. Two reasons, the second being the one that bit:
#   1. A 1500-bar M1 window spans ~25h, which aggregates to 8 H4 and 2 D1
#      bars. dailyBias (lib/setup/bias.ts) needs detectSwings, which needs
#      >= 2*swingLookback+1 = 5 bars, so the D1 arm returned "neutral"
#      unconditionally and S01 could never pass step 1 — whatever the market
#      did. The old comment here claimed 1500 was "enough for H4/D1
#      aggregation with headroom"; it was not, and nothing measured it.
#   2. A D1 bar aggregated from M1 is bucketed on UTC midnight, while the
#      broker's trading day (and every ICT notion of a daily candle) is the
#      server day — the same distinction T02a resolves for the day anchor.
#      Native bars carry the broker's own boundary for free.
# Counts are generous-but-cheap: these are a few hundred lines per file,
# rewritten on the same cadence as the M1 snapshot.
HTF_BARS = {
    "H1": 500,  # ~3 weeks
    "H4": 300,  # ~2 months
    "D1": 300,  # ~1 year
}


def resolve_broker_symbol(canonical: str) -> str | None:
    """Same resolution approach as log_spread.py / list_symbols.py (Phase 0)
    — duplicated rather than imported: those are throwaway measurement
    scripts, this is a production one, and the function is a handful of
    lines with no shared state to keep in sync."""
    if mt5.symbol_info(canonical) is not None:
        return canonical
    candidates = mt5.symbols_get(f"{canonical}*") or ()
    for s in candidates:
        if s.name.upper().startswith(canonical.upper()):
            return s.name
    return None


def export_spread(broker_name: str, out_path: Path) -> bool:
    """S01's cost gate reads spread live, never averaged (fiche, section
    'Portes de viabilité') — a small JSON snapshot alongside the M1 JSONL,
    not folded into the candle bars (OHLC carries no bid/ask)."""
    tick = mt5.symbol_info_tick(broker_name)
    info = mt5.symbol_info(broker_name)
    if tick is None or info is None or tick.bid <= 0 or tick.ask <= 0:
        return False
    out_path.write_text(
        json.dumps(
            {
                "symbol": broker_name,
                "bid": tick.bid,
                "ask": tick.ask,
                "spread": tick.ask - tick.bid,
                "point": info.point,
                "timestamp": int(time.time() * 1000),
            }
        ),
        encoding="utf-8",
    )
    return True


def export_symbol(broker_name: str, bars: int, out_path: Path, timeframe: str = "M1") -> int:
    mt5_timeframe = getattr(mt5, f"TIMEFRAME_{timeframe}")
    rates = mt5.copy_rates_from_pos(broker_name, mt5_timeframe, 0, bars)
    if rates is None or len(rates) == 0:
        return 0
    forming_index = len(rates) - 1  # only the newest bar may still be forming
    with out_path.open("w", encoding="utf-8") as f:
        for i, r in enumerate(rates):
            f.write(
                json.dumps(
                    {
                        "symbol": broker_name,
                        "timeframe": timeframe,
                        "openTime": int(r["time"]) * 1000,  # epoch ms UTC
                        "open": float(r["open"]),
                        "high": float(r["high"]),
                        "low": float(r["low"]),
                        "close": float(r["close"]),
                        "volume": int(r["tick_volume"]),
                        "closed": i != forming_index,
                    }
                )
                + "\n"
            )
    return len(rates)


def main() -> None:
    parser = argparse.ArgumentParser(description="Periodic M1 candle export for EA-02 (read-only)")
    parser.add_argument("--symbols", nargs="+", default=["EURUSD"])
    parser.add_argument("--bars", type=int, default=DEFAULT_BARS)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--out-dir", default=".")
    args = parser.parse_args()

    if not mt5.initialize():
        raise SystemExit(
            f"[export_m1] mt5.initialize() failed: {mt5.last_error()} "
            f"(is the MT5 terminal open and logged in?)"
        )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    resolved: dict[str, str] = {}
    for canonical in args.symbols:
        broker_name = resolve_broker_symbol(canonical)
        if broker_name is None:
            print(f"[export_m1] WARNING: no broker symbol found for {canonical!r}, skipping")
            continue
        mt5.symbol_select(broker_name, True)
        resolved[canonical] = broker_name
        print(f"[export_m1] {canonical} -> {broker_name}")

    if not resolved:
        mt5.shutdown()
        raise SystemExit("[export_m1] no symbol resolved, nothing to export")

    print(f"[export_m1] READ-ONLY. Exporting every {args.interval}s -> {out_dir}")

    try:
        while True:
            for canonical, broker_name in resolved.items():
                slug = canonical.lower()
                counts = {
                    "M1": export_symbol(broker_name, args.bars, out_dir / f"m1_{slug}.jsonl", "M1"),
                }
                for timeframe, bars in HTF_BARS.items():
                    counts[timeframe] = export_symbol(
                        broker_name, bars, out_dir / f"{timeframe.lower()}_{slug}.jsonl", timeframe
                    )
                export_spread(broker_name, out_dir / f"spread_{slug}.json")
                summary = ", ".join(f"{tf} {n}" for tf, n in counts.items())
                print(f"[export_m1] {canonical}: {summary} -> {out_dir}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[export_m1] stopped")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
