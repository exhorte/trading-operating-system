"""The journal routes' models."""

from __future__ import annotations

from trading_os.domain.journal.models import TradeCapture
from trading_os.domain.primitives import DomainModel


class TradeCaptures(DomainModel):
    """The two moments recorded around one position: the prices at its opening, and at its closing."""

    entry: TradeCapture | None
    exit: TradeCapture | None
