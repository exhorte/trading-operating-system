"""What the routes share: the account a request is about, and the bounds of the windows they let a client ask for.

``accountId`` is optional on every read — omitted, it means the **active account** (the one that receives automatic commands) —
and unknown ids are a 404, never silently another account. A write that could move money (a command, an intent to review) takes
the account in its body and has no default: the cockpit says which account it means.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Query

from trading_os.app.container import Container
from trading_os.shared.errors import Conflict, ValidationFailed

AccountQuery = Annotated[
    str | None, Query(alias="accountId", description="The account concerned; omitted, the active account.")
]
Limit = Annotated[int, Query(ge=1, le=500)]

DEFAULT_WINDOW = timedelta(days=30)
MAX_WINDOW = timedelta(days=366)


async def resolve_account(c: Container, account_id: str | None) -> str:
    """The id of an account that exists: the one asked for, or the active one when none was named."""
    if account_id is None:
        account_id = c.accounts.active_account_id
        if account_id is None:
            raise Conflict(
                "no active account: connect one, or name the account with accountId", code="no_active_account"
            )
    await c.accounts.get(account_id)  # NotFound if it is not one of ours
    return account_id


def resolve_window(
    now: datetime, start: datetime | None, end: datetime | None, *, default: timedelta = DEFAULT_WINDOW
) -> tuple[datetime, datetime]:
    """``[start, end]`` for a history query: ``end`` defaults to now, ``start`` to ``default`` before it; never inverted, never
    wider than a year (a query the database would have to chew on for nothing)."""
    end = end or now
    start = start or end - default
    if start >= end:
        raise ValidationFailed("start must be before end", code="invalid_window")
    if end - start > MAX_WINDOW:
        raise ValidationFailed("the window cannot exceed 366 days", code="window_too_wide")
    return start, end
