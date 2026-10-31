"""Canonical ↔ broker symbol names.

The domain speaks canonical codes (EURUSD, XAUUSD…); a terminal calls them what its broker decided
(Exness: ``EURUSDm``, FTMO: ``EURUSD``). This module only maps *names*. Specifications (tick value, contract size,
volume bounds) are **never** kept here: they come from the broker (``SymbolSpec``) — the static table that used to
live next to the names is what made position sizing wrong outside gold.
"""

from __future__ import annotations

from trading_os.domain.primitives import SymbolCode

# Canonical instruments the trader works. Extend deliberately: S01 itself is scoped by the strategy, not here.
KNOWN_CANONICAL: frozenset[SymbolCode] = frozenset({"EURUSD", "GBPUSD", "XAUUSD", "GBPJPY", "BTCUSD"})

# Broker suffixes observed on real terminals (Exness Standard accounts append "m").
KNOWN_SUFFIXES: tuple[str, ...] = ("m",)


def to_canonical(broker_name: str) -> SymbolCode | None:
    """``EURUSDm`` → ``EURUSD``; a canonical code is its own broker name (FTMO). ``None`` when unknown."""
    if broker_name in KNOWN_CANONICAL:
        return broker_name
    for suffix in KNOWN_SUFFIXES:
        if broker_name.endswith(suffix) and broker_name[: -len(suffix)] in KNOWN_CANONICAL:
            return broker_name[: -len(suffix)]
    return None


def to_broker(canonical: SymbolCode, suffix: str = "") -> SymbolCode:
    return f"{canonical}{suffix}"
