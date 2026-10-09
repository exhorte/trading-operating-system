"""The parameters S01 poses for its detectors (port of ``FX_DETECTION_CONFIG`` and the constants of ``scripts/run-setup-detection.ts``).

Provisional FX-scale defaults for EURUSD (5-digit quotes) — NOT the analysis engine's defaults, which are tuned for a gold price near
4000 (an ``equal_level_tolerance`` of 0.3 would be 3000 pips on EURUSD). Posed, not derived: to be revisited once an observation
sample exists. What S01 itself gives is marked « given »; everything else is a convention the user can change.

The cost threshold and the commission do not live here: they come from the account's execution limits (``ExecutionLimits``).
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import Field

from trading_os.domain.primitives import DomainModel, SymbolCode


class S01Config(DomainModel):
    # S01 v1 is scoped to EURUSD. GBPUSD was set aside on 2026-09-25 (user decision); XAUUSD stays out of scope until its thresholds
    # are ATR-relative.
    symbols: tuple[SymbolCode, ...] = ("EURUSD",)
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
