"""The risk routes' models. What the Risk Engine answers is the domain's own (``RiskStatus``, ``RiskDecision`` …); only what a
client *sends* is defined here."""

from __future__ import annotations

from pydantic import Field

from trading_os.api.schemas.common import StrictRequest
from trading_os.domain.primitives import AccountId, DomainModel, Side, SymbolCode
from trading_os.domain.risk.lockout import ActiveLockout, LockoutWindow
from trading_os.domain.strategy.intent import OrderKind


class ReviewRequest(StrictRequest):
    """A trade to be reviewed. It carries **no volume**: the Risk Engine sizes it from the stop and the account's rules, and
    only the approved decision it returns can open an execution command."""

    account_id: AccountId
    symbol: SymbolCode
    side: Side
    order_type: OrderKind = OrderKind.MARKET
    entry_price: float = Field(gt=0)  # the live price for a market order, the planned level otherwise
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    strategy_id: str = Field(default="manual", min_length=1, max_length=64)
    strategy_version: str = Field(default="0", min_length=1, max_length=32)
    rationale: str = Field(default="", max_length=500)
    valid_for_seconds: int = Field(default=60, ge=5, le=3600)  # how long the intent itself stays reviewable
    intent_id: str | None = Field(default=None, min_length=3, max_length=64)


class AccountRequest(StrictRequest):
    """A gesture on one account."""

    account_id: AccountId


class LockoutOverview(DomainModel):
    active: ActiveLockout | None  # the lockout in force right now, if any
    history: list[LockoutWindow]  # every lockout as recorded, newest information last


class AcknowledgeResult(DomainModel):
    lockout_id: str
