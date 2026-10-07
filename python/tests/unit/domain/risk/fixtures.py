"""Shared builders and realistic broker specifications for the risk tests (USD account).

The numbers are what an Exness Standard terminal reports (measured 2026-09-12 for EURUSD/GBPUSD/XAUUSD; the JPY
cross and the crypto follow the same MT5 conventions): ``tick_value`` is already in the account currency.
"""

from __future__ import annotations

from datetime import UTC, datetime

from trading_os.domain.market.models import SymbolSpec
from trading_os.domain.positions.models import Position
from trading_os.domain.primitives import Side
from trading_os.domain.risk.evaluate import RiskInputs
from trading_os.domain.risk.policy import RiskProfile

NOW = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)  # a Monday
ACCOUNT = "TEST-ACC-1"

EURUSD = SymbolSpec(
    name="EURUSDm",
    currency_base="EUR",
    currency_profit="USD",
    currency_margin="EUR",
    digits=5,
    point=0.00001,
    tick_size=0.00001,
    tick_value=1.0,
    tick_value_loss=1.0,
    contract_size=100_000,
    volume_min=0.01,
    volume_max=200.0,
    volume_step=0.01,
    stops_level_points=0,
)
GBPUSD = SymbolSpec(
    name="GBPUSDm",
    currency_base="GBP",
    currency_profit="USD",
    currency_margin="GBP",
    digits=5,
    point=0.00001,
    tick_size=0.00001,
    tick_value=1.0,
    tick_value_loss=1.0,
    contract_size=100_000,
    volume_min=0.01,
    volume_max=200.0,
    volume_step=0.01,
)
XAUUSD = SymbolSpec(
    name="XAUUSDm",
    currency_base="XAU",
    currency_profit="USD",
    currency_margin="XAU",
    digits=3,
    point=0.001,
    tick_size=0.001,
    tick_value=0.1,
    tick_value_loss=0.1,
    contract_size=100,
    volume_min=0.01,
    volume_max=200.0,
    volume_step=0.01,
)
# JPY-quoted cross on a USD account: MT5 converts the tick value (0.001 × 100 000 ÷ USDJPY 150 ≈ 0.6667 USD).
GBPJPY = SymbolSpec(
    name="GBPJPYm",
    currency_base="GBP",
    currency_profit="JPY",
    currency_margin="GBP",
    digits=3,
    point=0.001,
    tick_size=0.001,
    tick_value=0.66667,
    tick_value_loss=0.66667,
    contract_size=100_000,
    volume_min=0.01,
    volume_max=200.0,
    volume_step=0.01,
)
BTCUSD = SymbolSpec(
    name="BTCUSDm",
    currency_base="BTC",
    currency_profit="USD",
    currency_margin="BTC",
    digits=2,
    point=0.01,
    tick_size=0.01,
    tick_value=0.01,
    tick_value_loss=0.01,
    contract_size=1,
    volume_min=0.01,
    volume_max=50.0,
    volume_step=0.01,
)

SPECS = {s.name: s for s in (EURUSD, GBPUSD, XAUUSD, GBPJPY, BTCUSD)}


def profile(**overrides: object) -> RiskProfile:
    return RiskProfile(**overrides)


def inputs(**overrides: object) -> RiskInputs:
    """A flat 1000 USD account inside every limit, an agent connected, inside the London killzone."""
    base: dict[str, object] = {
        "account_id": ACCOUNT,
        "now": NOW,
        "profile": RiskProfile(),
        "initial_balance": 1000.0,
        "day_start_equity": 1000.0,
        "equity": 1000.0,
        "balance": 1000.0,
        "open_positions": 0,
        "trades_today": 0,
        "consecutive_losses": 0,
        "spread": 0.00008,
        "agent_connected": True,
        "in_trading_window": True,
        "window_label": "london",
        "calendar": (),
    }
    base.update(overrides)
    return RiskInputs(**base)


def position(position_id: str, symbol: str, side: Side, volume: float, entry: float, stop: float) -> Position:
    return Position(
        position_id=position_id,
        account_id=ACCOUNT,
        symbol=symbol,
        side=side,
        volume=volume,
        entry_price=entry,
        stop_loss=stop,
    )
