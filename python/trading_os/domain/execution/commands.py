"""Execution commands. ``command_id`` is the idempotency key: one id, at most one execution, ever."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from trading_os.domain.autonomy.state import AutonomyMode, ExecutionRoute
from trading_os.domain.primitives import AccountId, DomainModel, Side, SymbolCode
from trading_os.domain.strategy.intent import OrderKind


class CommandKind(StrEnum):
    OPEN = "OPEN"
    MODIFY = "MODIFY"
    CLOSE = "CLOSE"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    CANCEL = "CANCEL"

    @property
    def reduces_risk_only(self) -> bool:
        """Closing, partially closing or cancelling never adds exposure: no sizing, only a recorded approval."""
        return self in {CommandKind.CLOSE, CommandKind.PARTIAL_CLOSE, CommandKind.CANCEL}


class CommandState(StrEnum):
    PENDING = "PENDING"  # persisted, not yet sent
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"  # the agent accepted it (internally: received, validating, executing)
    EXECUTED = "EXECUTED"  # the broker filled it
    FAILED = "FAILED"  # a definite refusal: nothing is open
    UNKNOWN = "UNKNOWN"  # the outcome could not be observed — first-class, never replayed
    RECONCILING = "RECONCILING"
    RECONCILED = "RECONCILED"  # truth established from MT5 (terminal)
    REJECTED = "REJECTED"  # refused before any broker call (terminal)
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SIMULATED = "SIMULATED"  # paper broker, or an agent compiled OBSERVE: validated end to end, no broker order exists


class ExecutionRequest(DomainModel):
    """What a caller (API or strategy pipeline) asks the engine to do."""

    command_id: str = Field(min_length=3, max_length=64)
    account_id: AccountId
    kind: CommandKind = CommandKind.OPEN
    symbol: SymbolCode
    side: Side | None = None  # OPEN
    order_type: OrderKind = OrderKind.MARKET
    volume: float | None = Field(default=None, gt=0)  # OPEN, PARTIAL_CLOSE (lots)
    price: float | None = None  # limit/stop price; None for a market order
    stop_loss: float | None = None  # OPEN (mandatory), MODIFY
    take_profit: float | None = None
    strategy_id: str = "manual"
    strategy_version: str = "0"
    risk_decision_id: str | None = None
    position_id: str | None = None  # MODIFY, CLOSE, PARTIAL_CLOSE
    order_id: str | None = None  # CANCEL
    expires_at: datetime | None = None  # default: now + the account's command TTL


class ExecutionCommand(DomainModel):
    """A persisted command and everything learned about it. State only moves through ``state.transition``."""

    request: ExecutionRequest
    fingerprint: str
    state: CommandState
    route: ExecutionRoute
    mode: AutonomyMode  # autonomy mode at creation (audit)
    created_at: datetime
    expires_at: datetime
    sent_at: datetime | None = None
    acknowledged_at: datetime | None = None
    completed_at: datetime | None = None
    attempts: int = 0  # reconciliation attempts
    detail: str = ""
    reject_code: str | None = None
    broker_order_id: str | None = None
    broker_position_id: str | None = None
    filled_volume: float | None = None
    average_price: float | None = None
    broker_retcode: str | None = None

    @property
    def command_id(self) -> str:
        return self.request.command_id

    @property
    def account_id(self) -> str:
        return self.request.account_id
