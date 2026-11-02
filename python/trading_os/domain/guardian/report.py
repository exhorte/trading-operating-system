"""What the Account Guardian last saw and did for an account — the read model of ``GET /api/guardian``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from trading_os.domain.guardian.rules import GuardianVerdict
from trading_os.domain.guardian.watch import GuardianWatch
from trading_os.domain.primitives import DomainModel


class GuardianAction(DomainModel):
    kind: Literal["close", "cancel"]
    target_id: str  # the position or the pending order
    symbol: str
    reason: str
    status: Literal["shown", "submitted", "in_flight", "waiting", "gave_up", "skipped"]
    command_id: str | None = None
    detail: str = ""


class GuardianReport(DomainModel):
    account_id: str
    ran: bool = False  # False until the first cycle for this account
    at: datetime | None = None
    mode: str = ""  # the autonomy mode the cycle ran in
    verdict: GuardianVerdict = Field(default_factory=GuardianVerdict)
    actions: list[GuardianAction] = Field(default_factory=list)
    recovery: str | None = None  # what was found at the first cycle after the core started
    watch: GuardianWatch | None = (
        None  # the figures and findings of the last cycle (ADR 0032): spread, slippage, health, exposure…
    )
    # The last reconciliation the Guardian asked for and why (None = never asked): read-only towards the broker.
    reconciliation_asked: str | None = None
    reconciliation_asked_at: datetime | None = None
