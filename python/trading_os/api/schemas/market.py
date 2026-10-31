"""The market routes' models."""

from __future__ import annotations

from trading_os.domain.market.models import SymbolSpec, Tick
from trading_os.domain.primitives import DomainModel, SymbolCode


class MarketQuote(DomainModel):
    """One symbol as the account's terminal shows it: the last quote and the broker's specification."""

    symbol: SymbolCode
    tick: Tick | None  # None until a quote has been received
    spec: SymbolSpec | None  # None when the broker does not list the symbol
