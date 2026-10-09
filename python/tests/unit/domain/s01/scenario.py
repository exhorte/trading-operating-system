"""The reference S01 scenario (``lib/setup/proposal.test.ts``): a complete buy, built so that each step of the sequence is visible.

* H4 and D1 both show the same bullish break of structure -> a bullish daily bias;
* the 1H range has its last close in discount (below the 50 % line) -> a buy is allowed;
* the M1 context holds two far equal highs (105.0: the target), two equal lows (99.0: the sweep trigger) and a closer, more recent lone
  swing high (100.9: the level the displacement must break);
* the reaction sweeps 99.0 (low 98.7, close 99.2) and a big bullish body then closes at 110, leaving an unfilled FVG.

The entry-timeframe candles start at 07:00 UTC (London) so none falls in the Asia window, which keeps the Asia levels out of the scene.
"""

from __future__ import annotations

from tests.support.candles import candle_at, series
from trading_os.domain.market.models import Candle
from trading_os.domain.market.sessions import DEFAULT_SESSION_WINDOWS
from trading_os.domain.strategy.s01 import SetupProposalInput

BULLISH_HTF = series(
    [
        {"high": 10, "low": 8, "close": 9},
        {"high": 12, "low": 9, "close": 11},
        {"high": 11, "low": 9, "close": 10},
        {"high": 13, "low": 10, "close": 12.5},
    ]
)
BEARISH_HTF = series(
    [
        {"high": 12, "low": 10, "close": 11},
        {"high": 11, "low": 8, "close": 9},
        {"high": 11, "low": 9, "close": 10},
        {"high": 10, "low": 7, "close": 7.5},
    ]
)
H1_DISCOUNT = series(
    [
        {"high": 10, "low": 9, "close": 9.5},
        {"high": 9, "low": 8, "close": 8.5},
        {"high": 10, "low": 9, "close": 9.5},
        {"high": 12, "low": 10, "close": 11},
        {"high": 10, "low": 9, "close": 9.5},
    ]
)
H1_PREMIUM = series(
    [
        {"high": 10, "low": 9, "close": 9.5},
        {"high": 9, "low": 8, "close": 8.5},
        {"high": 10, "low": 9, "close": 9.5},
        {"high": 12, "low": 10, "close": 11},
        {"high": 10, "low": 9, "close": 9.5},
        {"high": 12, "low": 11, "close": 11.5},  # above the equilibrium
    ]
)


def at(i: int, high: float, low: float, *, open: float | None = None, close: float | None = None) -> Candle:
    return candle_at(420 + i, high, low, open=open, close=close, step_minutes=1, symbol="EURUSD")


CONTEXT = [
    at(0, 103.0, 102.5, close=102.8),
    at(1, 105.0, 102.6, close=102.9),  # swing high #1 of the far target cluster
    at(2, 102.9, 102.4, close=102.6),
    at(3, 102.5, 101.0, close=101.5),
    at(4, 105.0, 101.2, close=101.5),  # swing high #2 of the far target cluster
    at(5, 102.0, 100.0, close=100.2),
    at(6, 100.5, 99.0, close=99.3),  # swing low #1 of the trigger cluster
    at(7, 100.3, 99.5, close=99.8),
    at(8, 100.2, 99.6, close=100.0),  # kept flat so it does not form a spurious swing high
    at(9, 100.4, 99.0, close=99.4),  # swing low #2 of the trigger cluster
    at(10, 100.7, 99.7, close=100.3),
    at(11, 100.9, 99.8, close=100.5),  # the recent lone swing high -> the level to break
    at(12, 100.6, 99.85, close=100.3),
]

REACTION = [
    at(13, 99.4, 98.7, close=99.2),  # sweeps the 99.0 trigger level
    at(14, 99.5, 99.0, open=99.3, close=99.3),
    at(15, 99.7, 99.2, open=99.5, close=99.5),
    at(16, 99.9, 99.4, open=99.6, close=99.6),
    at(17, 110.3, 100.0, open=100.0, close=110.0),  # the displacement: a big body past 100.9 with an unfilled FVG
]


def base_input(**changes: object) -> SetupProposalInput:
    data: dict[str, object] = {
        "symbol": "EURUSD", "h4_candles": BULLISH_HTF, "d1_candles": BULLISH_HTF, "h1_candles": H1_DISCOUNT,
        "context_candles": CONTEXT, "reaction_candles": REACTION, "swing_lookback": 1, "equal_level_tolerance": 0.3,
        "session_windows": list(DEFAULT_SESSION_WINDOWS), "atr_period": 14, "min_body_atr_multiple": 1.5,
        "min_fvg_size": 0.2, "spread_buffer": 0.05, "spread": 0.1, "commission": 0.02, "cost_threshold": 0.25,
        "min_risk_reward": 3,
    }  # fmt: skip
    return SetupProposalInput.model_validate(data | changes)
