"""The first frame of every WebSocket (and of every resynchronisation): the whole state the cockpit draws, in one piece.

Built from the services' in-memory state wherever it exists (positions, quotes, risk, agents — what the cockpit would otherwise
learn from the events it missed) and from the database only for the short list of recent commands. Nothing here is computed:
the snapshot never answers a question the core has not already answered. Its shape is the ``CockpitSnapshot`` model, so the
cockpit's type for it is generated from the same definition as the rest of the API.
"""

from __future__ import annotations

from typing import Any

from trading_os import __version__
from trading_os.api.websocket.models import AccountState, CockpitSnapshot, HealthDigest
from trading_os.app.container import Container
from trading_os.shared.errors import Unavailable

RECENT_COMMANDS = 20


async def build_snapshot(c: Container, accounts: frozenset[str] | None = None) -> dict[str, Any]:
    states: dict[str, AccountState] = {}
    for account_id in c.accounts.connected_ids():
        if accounts is not None and account_id not in accounts:
            continue
        session = c.accounts.session(account_id)
        if session is None:
            continue
        try:
            commands = await c.execution.recent(account_id, RECENT_COMMANDS)
        except Unavailable:
            commands = []  # the database being down must not stop the cockpit from seeing the rest
        states[account_id] = AccountState(
            snapshot=c.positions.snapshot(account_id),
            positions=c.positions.positions(account_id),
            orders=c.positions.orders(account_id),
            quotes=[
                tick for name in c.market.watchlist(account_id) if (tick := c.market.tick(account_id, name)) is not None
            ],
            risk=c.risk.status(account_id),
            agent=c.execution.agent_status(str(session.account.login)),
            commands=commands,
        )
    snapshot = CockpitSnapshot(
        server_time=c.clock.now(),
        version=__version__,
        active_account_id=c.accounts.active_account_id,
        accounts=await c.accounts.accounts(),
        autonomy=await c.autonomy.overview(),
        health=HealthDigest(
            status=c.supervisor.status(), findings=c.supervisor.findings, checked_at=c.supervisor.last_tick_at
        ),
        calendar=c.news.snapshot(),
        account_states=states,
    )
    return snapshot.model_dump(mode="json", by_alias=True)
