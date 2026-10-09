"""What an AI assistant may read of the trader's own data — and nothing else (ADR 0005, « l'IA reste en lecture »).

Every function here **reads**: closed trades, the lockout ledger, candles as stored, S01's evaluations, what the reconciliation found,
and the compliance verdicts. None writes, none sends, none arms; none computes a performance figure (an expectancy, a win rate) — those
are facts for the person asking to reason about, not a score handed to them. ``tests/architecture`` fails if this package imports a
service that can act.

It reads the **database** through the journal service and the repositories: it starts no engine, opens no terminal, listens on no
socket. What lives only in the memory of a running core (live quotes, the risk gates right now) is not here — that is the cockpit's.

The account is configured once (``TRADING_OS_ACCOUNT_ID``, or ``ACTIVE_ACCOUNT_ID``): personal use, one account, never asked per call.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from trading_os.domain.primitives import Timeframe
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.services.journal import JournalService
from trading_os.shared.errors import ValidationFailed
from trading_os.shared.time import Clock, parse_when

MAX_CANDLES = 20_000
DIVERGENCE_LOOKBACK = timedelta(days=7)
DIVERGENCE_EVENTS = ("reconciliation.mismatch", "execution.reconciled", "execution.unknown")


def dump(value: Any) -> Any:
    """Pydantic models (camelCase, as the API shows them) and lists of them → plain JSON-ready data."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, list):
        return [dump(item) for item in value]
    return value


class ReadOnlyTools:
    def __init__(
        self, *, repos: Repositories, journal: JournalService, clock: Clock, account_id: Callable[[], str | None]
    ) -> None:
        self._repos = repos
        self._journal = journal
        self._clock = clock
        self._account_id = account_id

    def _account(self) -> str:
        account_id = self._account_id()
        if account_id is None:
            raise ValidationFailed(
                "no account configured: set TRADING_OS_ACCOUNT_ID (or ACTIVE_ACCOUNT_ID) once", code="no_account"
            )
        return account_id

    async def get_trades(self, start: str, end: str, symbol: str | None = None) -> list[dict[str, Any]]:
        """Closed trades in a range, newest first, with realised P&L, entry/exit, capture availability, the R multiple and the rules
        each broke. Facts only."""
        trades = await self._journal.trades(self._account(), parse_when(start), parse_when(end))
        return [dump(t) for t in trades if symbol is None or t.symbol == symbol]

    async def get_lockouts(self, until: str) -> list[dict[str, Any]]:
        """Every risk lockout window (kill switch, daily loss, consecutive-loss pause) up to a point in time."""
        return [dump(w) for w in await self._journal.lockouts(self._account(), parse_when(until))]

    async def get_candles(self, symbol: str, timeframe: str, start: str, end: str) -> dict[str, Any]:
        """OHLC candles as stored (raw price history — never a signal or a level), oldest first, capped at 20 000."""
        try:
            tf = Timeframe(timeframe)
        except ValueError as error:
            raise ValidationFailed(
                f"unknown timeframe {timeframe!r} (one of {', '.join(t.value for t in Timeframe)})",
                code="invalid_timeframe",
            ) from error
        candles = await self._repos.market.candles(symbol, tf, parse_when(start), parse_when(end))
        return {"truncated": len(candles) > MAX_CANDLES, "candles": dump(candles[:MAX_CANDLES])}

    async def get_setup_proposals(self, since: str) -> list[dict[str, Any]]:
        """S01's evaluations since a time — ``proposed`` (a candidate setup) and ``blocked`` (the stage where the sequence stopped).
        The measurement instrument of ADR 0011, never a signal to act on."""
        return [dump(e) for e in await self._repos.strategy.evaluations_since(parse_when(since))]

    async def get_execution_divergence(self) -> dict[str, Any]:
        """What the reconciliation found over the last seven days: commands still in doubt, commands settled from the broker's own
        history, and mismatches between the database and the broker — from the audit trail, as recorded."""
        account_id = self._account()
        since = self._clock.now() - DIVERGENCE_LOOKBACK
        events = await self._repos.events.query(
            types=list(DIVERGENCE_EVENTS), account_id=account_id, correlation_id=None, since=since, limit=200
        )
        return {
            "inDoubt": [dump(c) for c in await self._repos.execution.in_doubt(account_id)],
            "events": [
                {"type": e["type"], "occurredAt": e["occurred_at"].isoformat(), "payload": e["payload"]} for e in events
            ],
        }

    async def get_compliance_violations(self, start: str, end: str) -> dict[str, Any]:
        """The closed taxonomy of violations (lockout active, outside the session; the size policy needs the live balance, which a
        database-only reader does not have, so it is skipped rather than approximated) per closed trade in a range, and the resulting
        compliance rate. Recomputed from the facts on every call, never cached."""
        account_id = self._account()
        start_at, end_at = parse_when(start), parse_when(end)
        trades = await self._journal.trades(account_id, start_at, end_at)
        summary = await self._journal.compliance(account_id, start_at, end_at)
        return {
            "complianceRate": summary.rate,
            "trades": [
                {
                    "brokerPositionId": t.broker_position_id,
                    "closedAt": t.closed_at.isoformat(),
                    "violations": dump(t.violations),
                }
                for t in trades
            ],
        }
