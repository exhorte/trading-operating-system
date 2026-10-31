"""The audit trail subscriber: every event that is not telemetry is appended to the ``events`` table, once.

The table is the *history* of what the core said (orders created, decisions taken, faults seen, modes changed). It is not
where the core's truth lives — commands, risk decisions, lockouts, captures are written by their own services **before** they
act — so a write failing here must never hold anything up. It is counted instead, and the count is part of the health:
a silent gap in the audit trail would be the worst kind.
"""

from __future__ import annotations

import logging

from trading_os.infrastructure.database.repositories import Repositories
from trading_os.shared.errors import TradingOsError
from trading_os.shared.events.base import Event

logger = logging.getLogger(__name__)


class AuditTrail:
    def __init__(self, repos: Repositories) -> None:
        self._repos = repos
        self.written = 0
        self.lost = 0

    async def __call__(self, event: Event) -> None:
        if not event.persist:
            return
        try:
            if await self._repos.events.append(event):
                self.written += 1
        except TradingOsError as error:
            self.lost += 1
            if self.lost == 1 or self.lost % 100 == 0:
                logger.warning("audit trail: %d event(s) could not be recorded (%s)", self.lost, error.safe_message)
