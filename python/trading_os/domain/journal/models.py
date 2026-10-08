"""Journal facts. A trade is reconstructed from what was recorded at the real events, never recomputed later:
the capture rows are immutable (T05) and carry the window of candles the cockpit may draw — a boundary that is stored
and can never be widened, a stronger non-anticipation guarantee than a static image.

The server serves **facts and verdicts it can defend** (the trade, its captures, the rules it broke); the browser
aggregates and draws (``lib/account-analysis``): the figures a trader reads over a week are presentation, the question
« did this trade respect the rules? » is not, and is answered here, once (T07, migrated from the browser)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from trading_os.domain.execution.commands import ExecutionCommand
from trading_os.domain.primitives import AccountId, DomainModel, Side, SymbolCode
from trading_os.domain.risk.decision import RiskDecision
from trading_os.domain.strategy.intent import TradeIntent


class TradeCapture(DomainModel):
    account_id: AccountId
    broker_position_id: str
    kind: Literal["entry", "exit"]
    symbol: SymbolCode
    timeframe: str
    window_start_utc: datetime
    window_end_utc: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_price: float | None = None  # None on the entry row
    captured_at: datetime


class JournalTrade(DomainModel):
    broker_position_id: str
    symbol: SymbolCode
    side: Side
    volume: float
    entry_price: float | None
    exit_price: float
    realized_pnl: float
    stop_loss: float | None
    opened_at: datetime | None
    closed_at: datetime
    has_capture: bool


# ------------------------------------------------------------------------------------------------------ compliance (T07)


class ViolationType(StrEnum):
    """A closed taxonomy: three questions with data behind them. « Stop moved after entry » has no detector on purpose —
    nothing traced modifications until the position service started publishing them."""

    LOCKOUT_ACTIVE = "LOCKOUT_ACTIVE"
    SESSION_WINDOW = "SESSION_WINDOW"
    SIZE_POLICY = "SIZE_POLICY"


class Violation(DomainModel):
    type: ViolationType
    detail: str


class JournalTradeView(JournalTrade):
    """A closed trade as the journal lists it: the facts, the risk it took, and every rule it broke."""

    # What came back, in units of the risk taken at the stop; None when the entry or the stop are not on record.
    r_multiple: float | None = None
    violations: list[Violation] = Field(default_factory=list)


class ComplianceSummary(DomainModel):
    """Compliance over a set of trades. Judges nothing beyond what ``evaluate_trade`` judges: it counts and groups."""

    rate: float  # 0..1, and 1 on an empty window — there was nothing to violate
    trade_count: int
    breached_count: int  # trades carrying at least one violation
    by_type: dict[ViolationType, int]
    by_trade: dict[str, list[Violation]]  # keyed by broker position id


# ------------------------------------------------------------------------------------------------------ the file of a trade


class TradeFile(DomainModel):
    """Everything known about one position, from the strategy's intent to its outcome — the reconstruction the audit
    asks for (Intent → RiskDecision → Command → Position → Outcome). A position nobody commanded (opened by hand in MT5)
    has no intent, decision or command: it says so (``manual``) instead of inventing a chain."""

    account_id: AccountId
    broker_position_id: str
    status: Literal["open", "closed"]
    manual: bool
    trade: JournalTrade | None = None  # the closed trade's facts
    entry_capture: TradeCapture | None = None
    exit_capture: TradeCapture | None = None
    command: ExecutionCommand | None = None
    decision: RiskDecision | None = None
    intent: TradeIntent | None = None
    r_multiple: float | None = None
    violations: list[Violation] = Field(default_factory=list)
