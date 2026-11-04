"""What the terminal says about one instrument, **all of it**, and what it did not say (ADR 0036).

``InstrumentSpecification`` is a ``SymbolSpec`` (everything sizing needs, so nothing that already reads one changes) plus the
rest of what ``symbol_info`` carries: quotes, floating spread, trade and execution mode, filling modes, swaps, volume limit.
It is read from the terminal for the account that is connected — never from a table, never from the provider's website: a
documentary value is a bound, the terminal's value is the fact.

Anything the terminal did not give is listed in ``missing`` and stays ``None``: it is **never** replaced by a value that looks
plausible (a swap of 0 is a swap the terminal reported; no swap field is a swap nobody knows). ``missing_for_trading`` is the
part of the gap that stops an order; the rest is shown, not enforced.

The Python MetaTrader5 package exposes no trading sessions (``SymbolInfoSessionTrade`` is MQL5 only), so ``trading_sessions`` is
always ``None`` here and always listed as missing: the sessions can only come from the execution agent (a separate agreement).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pydantic import Field, ValidationError

from trading_os.domain.market.models import SymbolSpec

TRADE_MODES = {0: "DISABLED", 1: "LONG_ONLY", 2: "SHORT_ONLY", 3: "CLOSE_ONLY", 4: "FULL"}
EXECUTION_MODES = {0: "REQUEST", 1: "INSTANT", 2: "MARKET", 3: "EXCHANGE"}
SWAP_MODES = {
    0: "DISABLED",
    1: "POINTS",
    2: "CURRENCY_SYMBOL",
    3: "CURRENCY_MARGIN",
    4: "CURRENCY_DEPOSIT",
    5: "INTEREST_CURRENT",
    6: "INTEREST_OPEN",
    7: "REOPEN_CURRENT",
    8: "REOPEN_BID",
}
WEEKDAYS = {0: "SUNDAY", 1: "MONDAY", 2: "TUESDAY", 3: "WEDNESDAY", 4: "THURSDAY", 5: "FRIDAY", 6: "SATURDAY"}
FILLING_FLAGS = ((1, "FOK"), (2, "IOC"), (4, "BOC"))

# Fields without which an order cannot be placed or sized. Missing any of them is a refusal, not a footnote.
BLOCKING_FIELDS: frozenset[str] = frozenset(
    {"trade_mode", "execution_mode", "filling_mode", "stops_level", "freeze_level"}
)


class InstrumentSpecification(SymbolSpec):
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    spread_points: int | None = Field(default=None, ge=0)
    spread_floating: bool | None = None
    volume_limit: float | None = Field(default=None, ge=0)  # 0 = the broker sets none
    filling_modes: tuple[str, ...] = ()
    execution_mode: str | None = None
    trade_mode: str | None = None
    swap_long: float | None = None
    swap_short: float | None = None
    swap_mode: str | None = None
    swap_triple_day: str | None = None
    trading_sessions: tuple[str, ...] | None = None  # None: the Python terminal API does not expose them
    updated_at: datetime
    missing: tuple[str, ...] = ()
    provenance: str = "terminal"

    @property
    def missing_for_trading(self) -> tuple[str, ...]:
        return tuple(name for name in self.missing if name in BLOCKING_FIELDS)


def _present(raw: Mapping[str, Any], key: str) -> Any | None:
    value = raw.get(key)
    return None if value is None else value


def _name(mapping: Mapping[int, str], value: Any | None) -> str | None:
    return None if value is None else mapping.get(int(value), f"UNKNOWN({int(value)})")


def _filling_modes(flags: int) -> tuple[str, ...]:
    return tuple(name for bit, name in FILLING_FLAGS if flags & bit)


def specification_from_terminal(name: str, raw: Mapping[str, Any], *, now: datetime) -> InstrumentSpecification | None:
    """Build the specification of ``name`` from a ``symbol_info`` reply. ``None`` when what sizing needs is unusable (no contract
    size, no tick, no volume bounds): such a symbol cannot be traded at all, and the caller says so instead of guessing."""
    missing: list[str] = []

    def optional(key: str, label: str | None = None) -> Any | None:
        value = _present(raw, key)
        if value is None:
            missing.append(label or key)
        return value

    digits_raw = _present(raw, "digits")
    digits = int(digits_raw) if digits_raw is not None else 0
    tick_size = float(raw.get("trade_tick_size") or raw.get("point") or 0)
    loss = _present(raw, "trade_tick_value_loss")
    if not loss:
        missing.append("tick_value_loss")
    stops = optional("trade_stops_level", "stops_level")
    freeze = optional("trade_freeze_level", "freeze_level")
    trade_mode_raw = optional("trade_mode")
    execution_raw = optional("trade_exemode", "execution_mode")
    filling_raw = optional("filling_mode")
    if filling_raw is not None and int(filling_raw) == 0:
        missing.append("filling_mode")  # a symbol that allows no filling flag at all: not a usable reading
    swap_long = optional("swap_long")
    swap_short = optional("swap_short")
    swap_mode = _name(SWAP_MODES, _present(raw, "swap_mode"))
    if swap_mode is None:
        missing.append("swap_mode")
    triple_day = _name(WEEKDAYS, _present(raw, "swap_rollover3days"))
    if triple_day is None:
        missing.append("swap_triple_day")
    spread = optional("spread", "spread_points")
    spread_float = optional("spread_float", "spread_floating")
    volume_limit = optional("volume_limit")
    bid, ask, last = _present(raw, "bid"), _present(raw, "ask"), _present(raw, "last")
    # A zero bid or ask is the terminal's way of saying « no quote » (market closed, symbol not selected).
    bid_value = float(bid) if bid else None
    ask_value = float(ask) if ask else None
    if bid_value is None:
        missing.append("bid")
    if ask_value is None:
        missing.append("ask")
    missing.append("trading_sessions")  # never exposed by the Python API

    try:
        return InstrumentSpecification(
            name=name,
            description=raw.get("description", ""),
            currency_base=raw.get("currency_base", ""),
            currency_profit=raw.get("currency_profit", ""),
            currency_margin=raw.get("currency_margin", ""),
            digits=digits,
            point=float(raw.get("point") or 10**-digits),
            tick_size=tick_size,
            tick_value=float(raw.get("trade_tick_value_profit") or raw.get("trade_tick_value") or 0),
            tick_value_loss=float(loss) if loss else None,
            contract_size=float(raw.get("trade_contract_size", 0)),
            volume_min=float(raw.get("volume_min", 0)),
            volume_max=float(raw.get("volume_max", 0)),
            volume_step=float(raw.get("volume_step", 0)),
            stops_level_points=int(stops) if stops is not None else 0,
            freeze_level_points=int(freeze) if freeze is not None else 0,
            trade_allowed=trade_mode_raw is not None and int(trade_mode_raw) == 4,
            bid=bid_value,
            ask=ask_value,
            last=float(last) if last else None,
            spread_points=int(spread) if spread is not None else None,
            spread_floating=bool(spread_float) if spread_float is not None else None,
            volume_limit=float(volume_limit) if volume_limit is not None else None,
            filling_modes=_filling_modes(int(filling_raw)) if filling_raw is not None else (),
            execution_mode=_name(EXECUTION_MODES, execution_raw),
            trade_mode=_name(TRADE_MODES, trade_mode_raw),
            swap_long=float(swap_long) if swap_long is not None else None,
            swap_short=float(swap_short) if swap_short is not None else None,
            swap_mode=swap_mode,
            swap_triple_day=triple_day,
            trading_sessions=None,
            updated_at=now,
            missing=tuple(dict.fromkeys(missing)),
        )
    except (ValidationError, ValueError, TypeError):
        return None


__all__ = ["BLOCKING_FIELDS", "InstrumentSpecification", "specification_from_terminal"]
