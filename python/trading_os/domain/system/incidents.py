"""Incidents: a recorded abnormal situation (a halt, an unexpected position, a stale agent …) with who/what/when."""

from __future__ import annotations

from datetime import datetime

from trading_os.domain.primitives import DomainModel
from trading_os.domain.system.supervision import Severity


class Incident(DomainModel):
    incident_id: str
    code: str
    component: str
    severity: Severity
    detail: str
    opened_at: datetime
    account_id: str | None = None
    resolved_at: datetime | None = None
    resolution: str | None = None

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None
