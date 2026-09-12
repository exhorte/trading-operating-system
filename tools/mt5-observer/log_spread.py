"""
Throwaway spread measurement script — Phase 0 of the Vague EA plan
(02_Plan_Projet/prompt-claude-code-vague-ea.md).

NOT part of the domain, NOT a producer for the cockpit. It exists to turn the
provisional c-gate threshold (S01, "Portes de viabilite") from a documentary
guess into a real measurement, taken at the hours the strategy actually
trades. Delete it once enough sessions have been logged and the threshold is
calibrated.

Connects to MT5 exactly like mt5_observer.py (same mt5.initialize() /
mt5.symbol_info() pattern) but is a fully separate, read-only process:
  - no order call of any kind (grep this file: none exist);
  - no TimescaleDB write, no SignalR frame, no lib/contracts usage — this is
    a disposable measurement, not domain data (ADR 0009: a fact worth
    keeping is captured through the real pipeline, this isn't one);
  - safe to run alongside mt5_observer.py — both only read ticks.

Usage (Windows, terminal open and logged into the demo account):
    python log_spread.py --symbols EURUSD GBPUSD --out spread_log.jsonl

Broker symbol names can carry a suffix (e.g. EURUSDm on Exness). Pass the
canonical name (EURUSD); resolve_broker_symbol() finds the tradeable symbol
MT5 actually knows about, the same way mt5_observer.py's --symbol argument
is resolved by hand today.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5

SAMPLE_INTERVAL_SECONDS = 5


def resolve_broker_symbol(canonical: str) -> str | None:
    """Finds the exact broker symbol name for a canonical pair (e.g. EURUSD ->
    EURUSDm). Tries the bare name first, then scans mt5.symbols_get() for a
    name that starts with it — the common suffix pattern for this class of
    broker. Returns None if nothing matches."""
    if mt5.symbol_info(canonical) is not None:
        return canonical
    candidates = mt5.symbols_get(f"{canonical}*") or ()
    for s in candidates:
        if s.name.upper().startswith(canonical.upper()):
            return s.name
    return None


def sample(symbol: str) -> dict | None:
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None:
        return None
    point = info.point or 0.0
    # pip = 10 * point for a 5/3-digit symbol, point itself for a 4/2-digit
    # one — the same convention used across lib/analysis/ for FX pairs.
    pip_size = point * 10 if info.digits in (3, 5) else point
    spread_points = tick.ask - tick.bid
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "symbol": symbol,
        "bid": tick.bid,
        "ask": tick.ask,
        "spread_points": round(spread_points / point, 1) if point else None,
        "spread_pips": round(spread_points / pip_size, 2) if pip_size else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Throwaway MT5 spread logger (Phase 0)")
    parser.add_argument("--symbols", nargs="+", default=["EURUSD", "GBPUSD"])
    parser.add_argument("--out", default="spread_log.jsonl")
    parser.add_argument("--interval", type=float, default=SAMPLE_INTERVAL_SECONDS)
    args = parser.parse_args()

    if not mt5.initialize():
        raise SystemExit(
            f"[log_spread] mt5.initialize() failed: {mt5.last_error()} "
            f"(is the MT5 terminal open and logged in?)"
        )

    resolved: dict[str, str] = {}
    for canonical in args.symbols:
        broker_name = resolve_broker_symbol(canonical)
        if broker_name is None:
            print(f"[log_spread] WARNING: no broker symbol found for {canonical!r}, skipping")
            continue
        mt5.symbol_select(broker_name, True)
        resolved[canonical] = broker_name
        print(f"[log_spread] {canonical} -> {broker_name}")

    if not resolved:
        mt5.shutdown()
        raise SystemExit("[log_spread] no symbol resolved, nothing to log")

    out_path = Path(args.out)
    print(f"[log_spread] READ-ONLY. Sampling every {args.interval}s -> {out_path}")

    try:
        with out_path.open("a", encoding="utf-8") as f:
            while True:
                for broker_name in resolved.values():
                    row = sample(broker_name)
                    if row is not None:
                        f.write(json.dumps(row) + "\n")
                f.flush()
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[log_spread] stopped")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
