"""Asking for the same protective action again, without ever asking twice at once.

The Position Manager and the Account Guardian both submit commands of the same kind — « move this stop », « close this position » — from a
cycle that runs every couple of seconds. Their identifiers are deterministic (``<prefix>-<n>``), so a command is created once; this module
decides, from what the repository holds, whether the next attempt may be created yet:

* none exists: the first is (``new``);
* one is on its way (pending, sent, acknowledged, unknown, reconciling): wait for it (``in_flight``);
* the last ended without effect less than ``RETRY_AFTER`` ago: wait (``waiting``) — a refusal that comes back at once is not helped by
  asking again at once;
* ``MAX_ATTEMPTS`` ended without effect: stop asking (``gave_up``) — a human has to look. A loop is never the answer.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from trading_os.domain.execution.commands import CommandState
from trading_os.infrastructure.database.repositories import Repositories

IN_FLIGHT = frozenset(
    {
        CommandState.PENDING,
        CommandState.SENT,
        CommandState.ACKNOWLEDGED,
        CommandState.UNKNOWN,
        CommandState.RECONCILING,
    }
)
RETRY_AFTER = timedelta(seconds=60)
MAX_ATTEMPTS = 5

AttemptStatus = Literal["new", "in_flight", "waiting", "gave_up"]


async def next_attempt(repos: Repositories, prefix: str, now: datetime) -> tuple[str | None, AttemptStatus]:
    """The id of the next attempt at this action, or ``(None, why not yet)``. ``prefix`` is cut so every id fits the 64 characters."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        command_id = f"{prefix[: 64 - len(str(attempt)) - 1]}-{attempt}"
        existing = await repos.execution.get(command_id)
        if existing is None:
            return command_id, "new"
        if existing.state in IN_FLIGHT:
            return None, "in_flight"
        ended = existing.completed_at or existing.created_at
        if now - ended < RETRY_AFTER:
            return None, "waiting"
    return None, "gave_up"
