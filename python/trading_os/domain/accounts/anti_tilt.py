"""The anti-tilt rule (T12 incrément 2, ADR 0007): when does a change to an account's rules take effect?

**Immediately only when no session is in progress**: no trade opened since the day anchor on any account, no active
lockout on any account, a live account to look at, and no position open on it. Otherwise it waits for the first
trading-day anchor that starts after the request. The reference balance and the loss limits are the denominators of
both loss gates: raising one mid-session loosens the daily limit in money — the exact move this product exists to
prevent, hence the rule lives where the change is persisted, not in a disabled button.

« No live account » defers too: without a connection nothing can confirm that no position is open. **Every** account
is checked, not only the connected one — switching accounts in MT5 must not be enough to slip a change past the rule.

The reason codes, and their order, are stored with every deferred change (``deferral_reasons``): they are part of the ledger.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from trading_os.domain.primitives import DomainModel

NO_LIVE_ACCOUNT = "no_live_account"
OPEN_POSITIONS = "open_positions"
TRADES_TODAY = "trades_today"
ACTIVE_LOCKOUT = "active_lockout"


class SessionFact(DomainModel):
    """One account whose trading day is in progress (latest anchor less than 25 h old) or that is locked right now.
    25 and not 24: a DST night makes a 25-hour day, and when in doubt the rule counts one hour too many."""

    account_id: str
    day_anchor_starts_at_utc: datetime | None = None
    trades_today: int = 0
    active_lockout_reason: str | None = None


class LiveLink(DomainModel):
    """What the core sees of the terminal at this instant — never the page's belief."""

    connected: bool
    account_id: str | None
    open_positions: int = 0


class GuardReason(DomainModel):
    """Structured on purpose: the cockpit words it, the ledger stores it."""

    code: str
    account_id: str | None = None
    count: int | None = None
    detail: str | None = None


class GuardDecision(DomainModel):
    deferred: bool
    reasons: list[GuardReason]


def decide(link: LiveLink, sessions: Sequence[SessionFact]) -> GuardDecision:
    reasons: list[GuardReason] = []
    if not link.connected or link.account_id is None:
        reasons.append(GuardReason(code=NO_LIVE_ACCOUNT))
    elif link.open_positions > 0:
        reasons.append(GuardReason(code=OPEN_POSITIONS, account_id=link.account_id, count=link.open_positions))
    for session in sorted(sessions, key=lambda s: s.account_id):
        if session.trades_today > 0:
            reasons.append(GuardReason(code=TRADES_TODAY, account_id=session.account_id, count=session.trades_today))
        if session.active_lockout_reason is not None:
            reasons.append(
                GuardReason(code=ACTIVE_LOCKOUT, account_id=session.account_id, detail=session.active_lockout_reason)
            )
    return GuardDecision(deferred=bool(reasons), reasons=reasons)
