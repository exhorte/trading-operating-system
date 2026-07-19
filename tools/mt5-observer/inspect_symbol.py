"""
Read-only MT5 symbol/swap inspection (Phase 13 — pre-verdict capture).

Captures the broker's swap specification and trading constants for a symbol
from the locally running, already-logged-in MT5 terminal, normalizes swap to
USD/lot/night WHERE THE MODE ALLOWS IT (never assuming the raw values are
already USD/lot/night), and writes an auditable JSON capture with provenance.

STRICTLY READ-ONLY: imports only initialize/shutdown/*_info — zero trade
functions, zero credentials, same safety posture as mt5_observer.py.

Usage:
    python inspect_symbol.py --symbol XAUUSDm
    # writes swap_capture_<symbol>_<utc-date>.json next to this script
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5

# ENUM_SYMBOL_SWAP_MODE (MQL5 documentation).
SWAP_MODES = {
    0: "DISABLED",
    1: "POINTS",
    2: "CURRENCY_SYMBOL",   # base currency of the symbol (XAU for XAUUSD!)
    3: "CURRENCY_MARGIN",   # margin currency
    4: "CURRENCY_DEPOSIT",  # deposit (account) currency
    5: "INTEREST_CURRENT",  # annual % of current close price
    6: "INTEREST_OPEN",     # annual % of open price
    7: "REOPEN_CURRENT",    # position reopened at close price ± swap points
    8: "REOPEN_BID",        # position reopened at bid ± swap points
}

# ENUM_DAY_OF_WEEK (MQL5): 0=Sunday … 6=Saturday.
DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def normalize(mode: int, raw_swap: float, info, account_currency: str) -> dict:
    """USD/lot/night where derivable from the mode; otherwise mark manual.

    Never assumes raw_swap is already USD/lot/night — that is only true for
    CURRENCY_DEPOSIT on a USD account.
    """
    if mode == 0:
        return {"usdPerLotPerNight": 0.0, "method": "swap disabled (swap-free)", "confidence": "exact"}
    if mode == 1:
        # Swap quoted in points: USD value of one point for 1 lot is
        # tick_value scaled from tick_size to point size.
        if info.trade_tick_size <= 0:
            return {"usdPerLotPerNight": None, "method": "POINTS but tick_size<=0", "confidence": "manual_required"}
        point_value_usd = info.trade_tick_value * (info.point / info.trade_tick_size)
        return {
            "usdPerLotPerNight": raw_swap * point_value_usd,
            "method": f"POINTS: swap {raw_swap} x point value {point_value_usd:.5f} USD "
                      f"(tick_value {info.trade_tick_value} x point {info.point} / tick_size {info.trade_tick_size})",
            "confidence": "computed",
        }
    if mode == 4:
        if account_currency == "USD":
            return {"usdPerLotPerNight": raw_swap, "method": "CURRENCY_DEPOSIT on a USD account", "confidence": "exact"}
        return {
            "usdPerLotPerNight": None,
            "method": f"CURRENCY_DEPOSIT but account currency is {account_currency} — convert manually",
            "confidence": "manual_required",
        }
    if mode in (5, 6):
        # Annual percent of price; nightly estimate uses the industry 360-day
        # convention and TODAY'S price — an estimate, flagged as such.
        tick = mt5.symbol_info_tick(info.name)
        price = tick.bid if tick is not None else 0.0
        if price <= 0:
            return {"usdPerLotPerNight": None, "method": f"{SWAP_MODES[mode]} but no price available", "confidence": "manual_required"}
        nightly = price * info.trade_contract_size * (raw_swap / 100.0) / 360.0
        return {
            "usdPerLotPerNight": nightly,
            "method": f"{SWAP_MODES[mode]}: {raw_swap}%/year x price {price} x contract {info.trade_contract_size} / 360",
            "confidence": "estimate",
        }
    return {
        "usdPerLotPerNight": None,
        "method": f"{SWAP_MODES.get(mode, f'unknown mode {mode}')} — normalize manually before freezing",
        "confidence": "manual_required",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only swap/spec capture for one symbol")
    parser.add_argument("--symbol", default="XAUUSDm")
    args = parser.parse_args()

    if not mt5.initialize():
        raise SystemExit(f"[inspect] mt5.initialize() failed: {mt5.last_error()}")
    try:
        info = mt5.symbol_info(args.symbol)
        if info is None:
            raise SystemExit(f"[inspect] symbol {args.symbol!r} not found in Market Watch")
        mt5.symbol_select(args.symbol, True)
        info = mt5.symbol_info(args.symbol)  # refresh after select
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        account_currency = account.currency if account is not None else "unknown"

        mode = int(info.swap_mode)
        capture = {
            "capturedAtUtc": datetime.now(timezone.utc).isoformat(),
            "symbol": info.name,
            "raw": {
                "swap_mode": mode,
                "swap_mode_name": SWAP_MODES.get(mode, f"unknown ({mode})"),
                "swap_long": float(info.swap_long),
                "swap_short": float(info.swap_short),
                "swap_rollover3days": int(info.swap_rollover3days),
                "swap_rollover3days_name": DAYS[int(info.swap_rollover3days)] if 0 <= int(info.swap_rollover3days) <= 6 else "unknown",
                "trade_contract_size": float(info.trade_contract_size),
                "trade_tick_size": float(info.trade_tick_size),
                "trade_tick_value": float(info.trade_tick_value),
                "point": float(info.point),
                "digits": int(info.digits),
            },
            "normalized": {
                "long": normalize(mode, float(info.swap_long), info, account_currency),
                "short": normalize(mode, float(info.swap_short), info, account_currency),
                "note": "usdPerLotPerNight is null when the mode requires a manual conversion; "
                        "NEVER paste raw swap_long/short into the cost profile without the mode-aware conversion above.",
            },
            "provenance": {
                "accountLogin": account.login if account is not None else None,
                "accountCurrency": account_currency,
                "accountServer": account.server if account is not None else None,
                "accountCompany": account.company if account is not None else None,
                "terminalBuild": terminal.build if terminal is not None else None,
                "status": "captured from the logged-in terminal, read-only",
            },
        }
    finally:
        mt5.shutdown()

    out = Path(__file__).parent / f"swap_capture_{args.symbol}_{datetime.now(timezone.utc):%Y-%m-%d}.json"
    out.write_text(json.dumps(capture, indent=2), encoding="utf-8")
    print(json.dumps(capture, indent=2))
    print(f"\n[inspect] written to {out}")
    print("[inspect] next: confirm swap-free status in the Exness contract specs, then freeze the "
          "SwapSpec (or swap-free) into lib/backtest/costs.ts with this capture as provenance.")


if __name__ == "__main__":
    main()
