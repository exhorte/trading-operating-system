"""The first frame of every WebSocket (and of every resynchronisation): the whole state the cockpit draws, in one piece.

Built from the services' in-memory state wherever it exists (positions, quotes, risk, agents — what the cockpit would otherwise
learn from the events it missed) and from the database only for the short list of recent commands. Nothing here is computed:
the snapshot never answers a question the core has not already answered.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from trading_os import __version__
from trading_os.app.container import Container
from trading_os.shared.errors import Unavailable
from trading_os.shared.time import iso

RECENT_COMMANDS = 20


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True)


async def build_snapshot(c: Container, accounts: frozenset[str] | None = None) -> dict[str, Any]:
    now = c.clock.now()
    states: dict[str, Any] = {}
    for account_id in c.accounts.connected_ids():
        if accounts is not None and account_id not in accounts:
            continue
        session = c.accounts.session(account_id)
        if session is None:
            continue
        snapshot = c.positions.snapshot(account_id)
        risk = c.risk.status(account_id)
        agent = c.execution.agent_status(str(session.account.login))
        try:
            commands = [_dump(command) for command in await c.execution.recent(account_id, RECENT_COMMANDS)]
        except Unavailable:
            commands = []  # the database being down must not stop the cockpit from seeing the rest
        states[account_id] = {
            "snapshot": _dump(snapshot) if snapshot else None,
            "positions": [_dump(p) for p in c.positions.positions(account_id)],
            "orders": [_dump(o) for o in c.positions.orders(account_id)],
            "quotes": [
                _dump(tick)
                for name in c.market.watchlist(account_id)
                if (tick := c.market.tick(account_id, name)) is not None
            ],
            "risk": _dump(risk) if risk else None,
            "agent": _dump(agent) if agent else None,
            "commands": commands,
        }
    calendar = c.news.snapshot()
    return {
        "serverTime": iso(now),
        "version": __version__,
        "activeAccountId": c.accounts.active_account_id,
        "accounts": [_dump(a) for a in await c.accounts.accounts()],
        "autonomy": _dump(await c.autonomy.overview()),
        "health": {
            "status": c.supervisor.status().value,
            "findings": [_dump(f) for f in c.supervisor.findings],
            "checkedAt": iso(c.supervisor.last_tick_at) if c.supervisor.last_tick_at else None,
        },
        "calendar": _dump(calendar),
        "accountStates": states,
    }
