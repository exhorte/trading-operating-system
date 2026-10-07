"""The account-rules ledger: append-only versions, and which one applies right now.

A change is never an UPDATE — it is a new version, so « which rules applied on which day » stays answerable. The only
mutation allowed is stamping ``cancelled_at`` on a deferred change that has not governed any session yet.

Resolution runs against the **trading-day anchor of the account being traded** (the same one the daily loss uses): a
deferred change takes effect from the first anchor that starts after it was requested. Port of the pure part of
``lib/accounts/settings.ts``, now per account instead of per firm.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from pydantic import Field

from trading_os.domain.accounts.anti_tilt import GuardDecision, GuardReason
from trading_os.domain.accounts.models import AccountRules
from trading_os.domain.primitives import DomainModel
from trading_os.shared.ids import new_id


class RuleVersion(DomainModel):
    version_id: str
    account_id: str
    rules: AccountRules
    requested_at: datetime
    deferred: bool  # requested mid-session: applies from the next trading-day anchor
    deferral_reasons: list[GuardReason] = Field(default_factory=list)
    cancelled_at: datetime | None = None
    # A trading day has started since the request, on some account — the change may already have governed a session,
    # so it can no longer be withdrawn (undoing it is a change like any other).
    day_started_since: bool = False


class VersionStatus(StrEnum):
    IN_EFFECT = "in_effect"
    PENDING = "pending"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class CancelOutcome(StrEnum):
    CANCELLED = "cancelled"
    NOT_FOUND = "not_found"
    NOT_DEFERRED = "not_deferred"
    ALREADY_CANCELLED = "already_cancelled"
    ALREADY_IN_EFFECT = "already_in_effect"


def new_version(account_id: str, rules: AccountRules, decision: GuardDecision, now: datetime) -> RuleVersion:
    """A just-written row cannot have an anchor after it (anchors are day starts, never in the future)."""
    return RuleVersion(
        version_id=new_id("rules"),
        account_id=account_id,
        rules=rules,
        requested_at=now,
        deferred=decision.deferred,
        deferral_reasons=list(decision.reasons),
    )


def is_in_effect(version: RuleVersion, current_anchor: datetime | None) -> bool:
    """Not cancelled, and either applied at once or requested before the start of the current trading day. With no
    anchor known (nothing connected yet) a deferred change is *not* in effect — the conservative reading."""
    if version.cancelled_at is not None:
        return False
    if not version.deferred:
        return True
    return current_anchor is not None and current_anchor > version.requested_at


class RuleResolution(DomainModel):
    rules: AccountRules
    source: RuleVersion | None  # None = the account's built-in defaults (nothing in the ledger applies yet)
    pending: RuleVersion | None  # the latest change still waiting for the next trading day, if any


def resolve_rules(
    versions: Sequence[RuleVersion], current_anchor: datetime | None, default: AccountRules
) -> RuleResolution:
    own = sorted(versions, key=lambda v: v.requested_at, reverse=True)
    source = next((v for v in own if is_in_effect(v, current_anchor)), None)
    source_at = source.requested_at if source else None
    pending = next(
        (
            v
            for v in own
            if v.cancelled_at is None
            and not is_in_effect(v, current_anchor)
            and (source_at is None or v.requested_at > source_at)
        ),
        None,
    )
    return RuleResolution(rules=source.rules if source else default, source=source, pending=pending)


def version_status(version: RuleVersion, resolution: RuleResolution) -> VersionStatus:
    if version.cancelled_at is not None:
        return VersionStatus.CANCELLED
    source = resolution.source
    if source is not None and source.version_id == version.version_id:
        return VersionStatus.IN_EFFECT
    if source is not None and version.requested_at < source.requested_at:
        return VersionStatus.SUPERSEDED
    return VersionStatus.PENDING


def cancel_outcome(version: RuleVersion | None) -> CancelOutcome:
    """Whether a version may be withdrawn — the same four refusals as the database-side check."""
    if version is None:
        return CancelOutcome.NOT_FOUND
    if not version.deferred:
        return CancelOutcome.NOT_DEFERRED
    if version.cancelled_at is not None:
        return CancelOutcome.ALREADY_CANCELLED
    if version.day_started_since:
        return CancelOutcome.ALREADY_IN_EFFECT
    return CancelOutcome.CANCELLED


class DayAnchorState(DomainModel):
    account_id: str
    starts_at_utc: datetime | None


def next_day_anchor(current: DayAnchorState | None, incoming: DayAnchorState) -> DayAnchorState:
    """The anchor to keep when a new reading arrives. Within one account it only moves forward (a just-resolved
    anchor can reach the core before its row reaches the database, and a stale read must not put a change that just
    took effect back into « pending »). A different account replaces it outright: its server clock may legitimately
    be hours behind (FTMO CE(S)T vs Exness GMT)."""
    if current is None or current.account_id != incoming.account_id:
        return incoming
    if current.starts_at_utc is None:
        return incoming
    if incoming.starts_at_utc is None:
        return current
    return incoming if incoming.starts_at_utc >= current.starts_at_utc else current
