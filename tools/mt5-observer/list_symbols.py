"""
Throwaway one-shot script — Phase 0 of the Vague EA plan. Lists the exact
broker symbols behind EURUSD, GBPUSD and XAUUSD on the terminal currently
logged in, with the fields the symbol registry (EA-04) needs: exact name,
digits, point, tick value, minimum volume.

Read-only: mt5.symbol_info() / mt5.symbols_get() only, no order call.

Usage (Windows, terminal open and logged into the demo account):
    python list_symbols.py
    python list_symbols.py --canonical EURUSD GBPUSD XAUUSD USDJPY
"""

from __future__ import annotations

import argparse

import MetaTrader5 as mt5


def find_matches(canonical: str) -> list:
    exact = mt5.symbol_info(canonical)
    matches = list(mt5.symbols_get(f"{canonical}*") or ())
    if exact is not None and exact.name not in {m.name for m in matches}:
        matches.append(exact)
    return matches


def main() -> None:
    parser = argparse.ArgumentParser(description="List broker symbols for canonical pairs (Phase 0)")
    parser.add_argument("--canonical", nargs="+", default=["EURUSD", "GBPUSD", "XAUUSD"])
    args = parser.parse_args()

    if not mt5.initialize():
        raise SystemExit(
            f"[list_symbols] mt5.initialize() failed: {mt5.last_error()} "
            f"(is the MT5 terminal open and logged in?)"
        )

    try:
        for canonical in args.canonical:
            matches = find_matches(canonical)
            if not matches:
                print(f"# {canonical}: no matching broker symbol found")
                continue
            for s in matches:
                print(f"# {canonical} -> {s.name}")
                print(f"  digits       = {s.digits}")
                print(f"  point        = {s.point}")
                print(f"  trade_tick_value = {s.trade_tick_value}")
                print(f"  trade_tick_size  = {s.trade_tick_size}")
                print(f"  volume_min   = {s.volume_min}")
                print(f"  volume_max   = {s.volume_max}")
                print(f"  volume_step  = {s.volume_step}")
                print(f"  trade_stops_level = {s.trade_stops_level}")
                print()
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
