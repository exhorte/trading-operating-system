"""S01 setup-proposal model (port of ``lib/domain/setup.ts``): what the detection pipeline hands upstream once every step of the
sweep-aligned sequence has passed.

A strategy proposes; the Risk Engine decides (ADR 0007). Nothing here is a decision, and nothing here has been sized or approved yet.
Vocabulary source: ``context/product/tools/S01-strategie-sweep-aligne.md``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from trading_os.domain.market.analysis.models import LiquidityKind
from trading_os.domain.primitives import DomainModel, Side, SymbolCode


class SetupProposal(DomainModel):
    """A completed S01 proposal. Never an order, never a decision."""

    proposal_id: str
    symbol: SymbolCode
    side: Side
    swept_level_kind: LiquidityKind  # the pool whose sweep triggered this proposal (S01 step 4)
    swept_level_price: float
    entry_price: float
    stop_loss: float
    take_profit: float  # the opposite external liquidity — the trade's objective (S01 step 3)
    cost_ratio: float  # c = round-trip cost / stop distance (S01 « porte de coût »)
    risk_reward_ratio: float  # R:R from entry to take-profit, after cost (S01 « porte R:R »)
    detected_at: datetime


class SetupStage(StrEnum):
    """Where the S01 sequence stopped when it did not reach a proposal — the whole point of the measurement (ADR 0011): the exact
    stage says WHY the machine proposed nothing.

    The five ``PRECONDITION_*`` stages are evaluated by whatever orchestrates the pipeline live BEFORE it runs (S01: « si une
    seule précondition manque, il n'y a pas de recherche »); ``evaluate_setup`` itself never returns them.
    """

    PRECONDITION_SESSION_WINDOW = "precondition_session_window"
    PRECONDITION_NY_LUNCH = "precondition_ny_lunch"
    PRECONDITION_CALENDAR = "precondition_calendar"
    PRECONDITION_LOCKOUT = "precondition_lockout"
    PRECONDITION_TRADES_LIMIT = "precondition_trades_limit"
    BIAS = "bias"
    DEALING_RANGE = "dealing_range"
    RANGE_LOCATION = "range_location"
    LIQUIDITY = "liquidity"
    SWEEP = "sweep"
    OPPOSITE_SWING = "opposite_swing"
    DISPLACEMENT = "displacement"
    POI = "poi"
    STOP = "stop"
    GATES = "gates"


class ProposedOutcome(DomainModel):
    status: Literal["proposed"] = "proposed"
    proposal: SetupProposal


class BlockedOutcome(DomainModel):
    status: Literal["blocked"] = "blocked"
    stage: SetupStage
    detail: str


SetupOutcome = Annotated[ProposedOutcome | BlockedOutcome, Field(discriminator="status")]
