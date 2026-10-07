"""What the execution agent reported, as the core records it (the wire models stay in infrastructure)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from trading_os.domain.primitives import AccountId, DomainModel, SymbolCode


class AckRecord(DomainModel):
    command_id: str
    agent_id: str
    status: Literal["ACCEPTED", "REJECTED", "DUPLICATE", "EXPIRED"]
    reason: str | None = None
    received_at: datetime


class ReportRecord(DomainModel):
    report_id: str
    command_id: str
    account_id: AccountId
    agent_id: str
    symbol: SymbolCode
    side: str
    status: str
    detail: str
    reported_at: datetime


class ReconciliationRecord(DomainModel):
    command_id: str
    account_id: AccountId
    outcome: Literal["executed", "rejected", "not_found"]
    symbol: SymbolCode | None = None
    side: str | None = None
    broker_order_id: str | None = None
    broker_position_id: str | None = None
    filled_volume: float | None = None
    average_price: float | None = None
    broker_retcode: str | None = None
    attempts: int
    detail: str
    reconciled_at: datetime


class PositionScanRecord(DomainModel):
    """The agent's own view of an open position (EA-06): who opened it, and whether it is one of ours."""

    account_id: AccountId
    broker_position_id: str
    symbol: SymbolCode
    side: str
    volume: float
    magic_number: int
    is_external: bool
    known_command_id: str | None = None
    scanned_at: datetime
