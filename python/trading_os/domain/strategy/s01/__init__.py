"""S01 — the sweep-aligned strategy (port of ``lib/setup``): the user's own formalised rules, as pure functions.

The sequence is bias (H4+D1) → dealing range (1H) → liquidity map → sweep → displacement/MSS → point of interest → stop → viability
gates → a ``SetupProposal``. A proposal is not an order and not a decision: it goes to the Risk Engine (ADR 0007), which sizes it and
approves or refuses it. Nothing here executes, schedules or reads a database; the runtime that feeds it candles is
``services/strategy``. Equivalence with the TypeScript original is held by golden vectors (``tests/golden/s01.json``).
"""

from __future__ import annotations

from trading_os.domain.strategy.s01.models import (
    BlockedOutcome,
    ProposedOutcome,
    SetupOutcome,
    SetupProposal,
    SetupStage,
)
from trading_os.domain.strategy.s01.proposal import SetupProposalInput, evaluate_setup, propose_setup

__all__ = [
    "BlockedOutcome",
    "ProposedOutcome",
    "SetupOutcome",
    "SetupProposal",
    "SetupProposalInput",
    "SetupStage",
    "evaluate_setup",
    "propose_setup",
]
