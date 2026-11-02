"""Guardian: what the Account Guardian last saw and did (ADR 0025). Read-only — it acts through the execution engine, never from a route."""

from __future__ import annotations

from fastapi import APIRouter

from trading_os.api.params import AccountQuery, resolve_account
from trading_os.app.dependencies import Core
from trading_os.domain.guardian.report import GuardianReport

router = APIRouter(prefix="/api/guardian", tags=["guardian"])


@router.get(
    "", response_model=GuardianReport,
    summary="The Account Guardian's last verdict: limits reached, positions without a stop, what it asked for, what it found at startup",
)  # fmt: skip
async def last_report(c: Core, account_id: AccountQuery = None) -> GuardianReport:
    return c.guardian.report(await resolve_account(c, account_id))
