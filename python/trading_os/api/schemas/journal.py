"""The journal routes' models."""

from __future__ import annotations

from trading_os.domain.journal.models import TradeCapture
from trading_os.domain.primitives import DomainModel


class TradeCaptures(DomainModel):
    """The two moments recorded around one position."""

    entry: TradeCapture | None
    exit: TradeCapture | None
