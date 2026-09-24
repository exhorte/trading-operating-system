"""
Read-only probe of the MT5 terminal currently open — T12 incrément 2.

Answers what scripts/start-live.ps1 needs before starting the observer,
without a credential and without any order call:
  * which account the terminal is logged into (login, broker, server, demo
    or real) — so the trader sees which account the cockpit is about to follow;
  * which firm that broker is — the same substring rule as
    lib/accounts/firm.ts (default recognition texts);
  * which gold symbol to observe — FTMO names it XAUUSD, Exness XAUUSDm
    (lib/accounts/connection.ts, lib/market/symbols/registry.ts), and
    mt5_observer.py stops on « symbol not found » when started with the
    other one. Chosen by firm, never by "first name that starts with XAUUSD":
    an Exness terminal also lists XAUUSD247m (continuous quoting), which is
    not the instrument the cockpit's spread gate is calibrated for.

Like mt5_observer.py it attaches with mt5.initialize() and no login: the
terminal is already authenticated by the trader (ADR 0003). Prints one JSON
object on stdout; exit code 1 when the terminal cannot be reached or is not
logged into an account.

    python tools/mt5-observer/probe_terminal.py
"""

from __future__ import annotations

import json
import sys

import MetaTrader5 as mt5

# Mirrors lib/accounts/firm.ts (DEFAULT_BROKER_MATCHERS, same order) and
# lib/accounts/connection.ts (terminalSymbol for XAUUSD).
FIRM_MATCHERS = (("ftmo", "ftmo"), ("exness", "exness"))
GOLD_SYMBOL = {"ftmo": "XAUUSD", "exness": "XAUUSDm"}
GOLD_CANDIDATES = ("XAUUSD", "XAUUSDm")
TRADE_MODES = {0: "demo", 1: "contest", 2: "real"}


def detect_firm(company: str | None) -> str | None:
    name = (company or "").lower()
    for firm, needle in FIRM_MATCHERS:
        if needle in name:
            return firm
    return None


def choose_gold_symbol(firm: str | None, available: dict[str, bool]) -> str | None:
    """The firm's own name for gold if this terminal lists it. For a
    recognised firm whose name is missing, None — saying so beats silently
    observing another instrument. For an unrecognised broker, whichever of
    the two known names exists."""
    if firm is not None:
        preferred = GOLD_SYMBOL[firm]
        return preferred if available.get(preferred) else None
    for candidate in GOLD_CANDIDATES:
        if available.get(candidate):
            return candidate
    return None


def main() -> int:
    if not mt5.initialize():
        print(json.dumps({"error": f"mt5.initialize() failed: {mt5.last_error()}"}))
        return 1
    try:
        info = mt5.account_info()
        if info is None:
            print(json.dumps({"error": "terminal open but not logged into any account"}))
            return 1
        available = {name: mt5.symbol_info(name) is not None for name in GOLD_CANDIDATES}
        firm = detect_firm(info.company)
        print(json.dumps({
            "login": str(info.login),
            "company": info.company,
            "server": info.server,
            "tradeMode": TRADE_MODES.get(info.trade_mode, str(info.trade_mode)),
            "currency": info.currency,
            "firm": firm,
            "goldSymbols": available,
            "observerSymbol": choose_gold_symbol(firm, available),
        }))
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    sys.exit(main())
