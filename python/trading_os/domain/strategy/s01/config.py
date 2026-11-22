"""The parameters S01 poses for its detectors (port of ``FX_DETECTION_CONFIG`` and the constants of the former TypeScript detection worker).

Provisional FX-scale defaults for EURUSD (5-digit quotes) — NOT the analysis engine's defaults, which are tuned for a gold price near
4000 (an ``equal_level_tolerance`` of 0.3 would be 3000 pips on EURUSD). Posed, not derived: to be revisited once an observation
sample exists. What S01 itself gives is marked « given »; everything else is a convention the user can change.

The cost threshold and the commission do not live here: they come from the account's execution limits (``ExecutionLimits``).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Self

from pydantic import Field

from trading_os.domain.market.sessions import S01_TRADING_WINDOWS, TradingWindow
from trading_os.domain.primitives import DomainModel, SymbolCode


class SymbolScale(DomainModel):
    """The thresholds of S01 written in price units, for one symbol whose price is not on the EURUSD's scale (ADR 0043). Posed, not derived
    (ADR 0002): the same relative geometry as the EURUSD values below, nothing searched."""

    equal_level_tolerance: float = Field(ge=0)
    min_fvg_size: float = Field(gt=0)
    spread_buffer: float = Field(ge=0)
    level_decimals: int = Field(ge=0, le=8)


# BTCUSD (ADR 0043, 2026-11-14): a price ≈ 58 600 × the EURUSD's, so 3 pips → 18 USD, 1 pip → 6 USD; the spread buffer is 1.25 × the 6.40 USD
# spread measured on the demo (as 1 pip ≈ 1.25 × the EURUSD's 0.8-pip spread); levels rounded to the dollar.
BTCUSD_SCALE = SymbolScale(equal_level_tolerance=18.0, min_fvg_size=6.0, spread_buffer=8.0, level_decimals=0)


class S01Config(DomainModel):
    # S01 v1 was scoped to EURUSD (GBPUSD set aside on 2026-09-25, a user decision); BTCUSD joined it on 2026-11-14 (ADR 0043) with its own
    # scale. XAUUSD stays out of scope until its thresholds are posed. The symbols are a setting: ``STRATEGY_S01_SYMBOLS``.
    symbols: tuple[SymbolCode, ...] = ("EURUSD",)
    # Thresholds in price units, per symbol, for symbols not on the EURUSD's scale: the fields below are the EURUSD's.
    symbol_scales: dict[SymbolCode, SymbolScale] = Field(default_factory=lambda: {"BTCUSD": BTCUSD_SCALE})
    swing_lookback: int = Field(default=2, ge=1)
    equal_level_tolerance: float = Field(default=0.0003, ge=0)  # 3 pips
    min_fvg_size: float = Field(default=0.0001, gt=0)  # 1 pip
    atr_period: int = Field(default=14, ge=1)
    min_body_atr_multiple: float = Field(default=1.5, gt=0)  # S01 step 5 — given
    spread_buffer: float = Field(default=0.0001, ge=0)  # 1 pip
    min_risk_reward: float = Field(default=3.0, gt=0)  # S01 « porte R:R » — given
    # how many of the latest M1 candles are the reaction window (the rest is the context a sweep is looked for against)
    reaction_window_m1_bars: int = Field(default=30, ge=5)
    # bars read per timeframe: native, never aggregated (an M1 window aggregated to D1 holds 2 bars and the daily bias could never leave
    # neutral — the reason the exporter pulls them natively)
    m1_bars: int = Field(default=1500, ge=100)  # ~25h of M1
    h1_bars: int = Field(default=500, ge=20)  # ~3 weeks
    h4_bars: int = Field(default=300, ge=20)  # ~2 months
    d1_bars: int = Field(default=300, ge=20)  # ~1 year
    map_bars: int = Field(default=400, ge=20)  # 15-minute bars of the map a variant reads (S02): ~4 days
    # Decimals kept by the equal highs/lows and previous-day levels. 2 is the original's — and gold's: on EURUSD it rounds a level of
    # 1.0830 to 1.08, up to 50 pips away, so the sweep of the true cluster is never seen. Kept at 2 so the port behaves exactly like the
    # strategy the user observed; setting it to the symbol's digits is a one-value correction that is the user's to take.
    level_decimals: int = Field(default=2, ge=0, le=8)
    # a proposal older than this is recorded (it is the measurement) but never handed to the Risk Engine: the market has moved
    act_within: timedelta = timedelta(minutes=3)
    # how long a TradeIntent stays reviewable
    intent_ttl: timedelta = timedelta(minutes=2)
    # no evaluation more often than this (the same closed candle never evaluates twice anyway)
    min_interval: timedelta = timedelta(seconds=20)
    # The hours the strategy looks for a setup, New York local time (DST-aware): S01's historical killzones. Posed, not derived. A
    # variant has its own (S02's are not these); the settings can replace them (``STRATEGY_S01_WINDOWS``).
    trading_windows: tuple[TradingWindow, ...] = S01_TRADING_WINDOWS

    def for_symbol(self, canonical: SymbolCode | None) -> Self:
        """The configuration one symbol is evaluated with: its own scale where one is posed, the EURUSD-scale values otherwise."""
        scale = self.symbol_scales.get(canonical or "")
        return self if scale is None else self.model_copy(update=scale.model_dump())
