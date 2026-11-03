"""S02's parameters (ADR 0024, amended). Thresholds are S01's and are *posed*; the structure follows notes N5 and N6.

What the mission names without numbers (a deeper entry level, a breaker block, a different target) is not guessed here: it is for the
user to write. XAUUSD stays out until its thresholds are ATR-relative, as for S01.
"""

from __future__ import annotations

from pydantic import Field

from trading_os.domain.market.sessions import S02_TRADING_WINDOWS, TradingWindow
from trading_os.domain.strategy.s01.config import S01Config


class S02Config(S01Config):
    # N5: the limit rests at the EDGE of the FVG (0 = the edge price reaches first; 0.5 would be the CE, 1 the far edge).
    entry_fraction: float = Field(default=0.0, ge=0, le=1)
    # ADR 0030: S02's hours are its own, not S01's — New York AM 08:30–11:00 (notes N4, N5, N6) and the London killzone 02:00–05:00,
    # both New York local time. Replaceable through ``STRATEGY_S02_WINDOWS``.
    trading_windows: tuple[TradingWindow, ...] = S02_TRADING_WINDOWS
