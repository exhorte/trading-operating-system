"""Risk facts: the trading-day anchor, the lockout ledger, kill-switch acknowledgements, and every risk decision.

The lockout ledger is the source of truth for « locked right now » — never re-derived purely from live gate evaluation.
It is append-only: a lockout is opened once and later *stamped* cleared, never rewritten.
"""

from __future__ import annotations

from datetime import datetime

from trading_os.domain.risk.decision import RiskDecision
from trading_os.domain.risk.lockout import ActiveLockout, LockoutWindow
from trading_os.domain.risk.trading_day import (
    MAX_RECENT_CLOSED_TRADES,
    RiskToday,
    StreakTrade,
    count_consecutive_losses,
)
from trading_os.infrastructure.database.pool import Database, Row, jsonb


def _to_lockout(row: Row) -> ActiveLockout:
    return ActiveLockout(lockout_id=row["lockout_id"], reason=row["reason"], since=row["since"], until=row["until"])


class RiskRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------------------------------ trading day
    async def record_anchor(self, account_id: str, starts_at_utc: datetime) -> None:
        await self._db.execute(
            "INSERT INTO trading_day_anchors (account_id, starts_at_utc) VALUES (%s, %s) "
            "ON CONFLICT (account_id, starts_at_utc) DO NOTHING",
            (account_id, starts_at_utc),
        )

    async def confirm_day_start_equity(self, account_id: str, starts_at_utc: datetime, equity: float) -> bool:
        """Fills a still-unknown equity of that anchor — never overwrites one already captured."""
        updated = await self._db.execute(
            "UPDATE trading_day_anchors SET day_start_equity = %s "
            "WHERE account_id = %s AND starts_at_utc = %s AND day_start_equity IS NULL",
            (equity, account_id, starts_at_utc),
        )
        return updated == 1

    async def today(self, account_id: str, now: datetime) -> RiskToday:
        anchor = await self._db.fetch_one(
            "SELECT starts_at_utc, day_start_equity FROM trading_day_anchors WHERE account_id = %s "
            "ORDER BY starts_at_utc DESC LIMIT 1",
            (account_id,),
        )
        trades_today = 0
        if anchor is not None:
            trades_today = int(
                await self._db.fetch_value(
                    "SELECT count(*) FROM position_opens WHERE account_id = %s AND opened_at >= %s",
                    (account_id, anchor["starts_at_utc"]),
                )
            )
        # The loss streak never resets at the day anchor: a losing streak spanning midnight is still a streak.
        closed = await self._db.fetch_all(
            "SELECT realized_pnl, closed_at FROM closed_trades WHERE account_id = %s ORDER BY closed_at DESC LIMIT %s",
            (account_id, MAX_RECENT_CLOSED_TRADES),
        )
        losses, last_loss_at = count_consecutive_losses(
            StreakTrade(realized_pnl=r["realized_pnl"], closed_at=r["closed_at"]) for r in closed
        )
        return RiskToday(
            day_anchor_starts_at_utc=anchor["starts_at_utc"] if anchor else None,
            day_start_equity=anchor["day_start_equity"] if anchor else None,
            trades_today=trades_today,
            consecutive_losses=losses,
            last_loss_at=last_loss_at,
            active_lockout=await self.active_lockout(account_id, now),
        )

    # ------------------------------------------------------------------------------------------ lockouts
    async def active_lockout(self, account_id: str, now: datetime) -> ActiveLockout | None:
        """An expired timed pause must not read back as active right after expiry (stamping it cleared is
        ``clear_lockout``'s other job, so this is the backup path)."""
        row = await self._db.fetch_one(
            "SELECT lockout_id, reason, since, until FROM risk_lockouts "
            "WHERE account_id = %s AND cleared_at IS NULL AND (until IS NULL OR until > %s) "
            "ORDER BY since DESC LIMIT 1",
            (account_id, now),
        )
        return _to_lockout(row) if row else None

    async def open_lockout(
        self, lockout_id: str, account_id: str, reason: str, since: datetime, until: datetime | None
    ) -> None:
        await self._db.execute(
            "INSERT INTO risk_lockouts (lockout_id, account_id, reason, since, until) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (lockout_id) DO NOTHING",
            (lockout_id, account_id, reason, since, until),
        )

    async def clear_lockout(self, account_id: str, cleared_by: str, at: datetime) -> str | None:
        """Stamps every uncleared lockout of the account as cleared and returns the id of the one that was *active*
        (there is never more than one: opening is edge-triggered), or None when nothing was locked. A timed pause
        whose clock had already run out is stamped ``pause-expired`` rather than attributed to ``cleared_by``."""
        rows = await self._db.fetch_all(
            "UPDATE risk_lockouts SET cleared_at = %s, "
            "cleared_by = CASE WHEN until IS NOT NULL AND until <= %s THEN 'pause-expired' ELSE %s END "
            "WHERE account_id = %s AND cleared_at IS NULL "
            "RETURNING lockout_id, (until IS NULL OR until > %s) AS was_active",
            (at, at, cleared_by, account_id, at),
        )
        return next((r["lockout_id"] for r in rows if r["was_active"]), None)

    async def acknowledge(self, account_id: str, lockout_id: str, at: datetime) -> None:
        await self._db.execute(
            "INSERT INTO kill_switch_acks (account_id, lockout_id, acknowledged_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (account_id, lockout_id) DO NOTHING",
            (account_id, lockout_id, at),
        )

    async def lockout_history(self, account_id: str, up_to: datetime) -> list[LockoutWindow]:
        rows = await self._db.fetch_all(
            "SELECT lockout_id, reason, since, until, cleared_at FROM risk_lockouts "
            "WHERE account_id = %s AND since <= %s ORDER BY since ASC",
            (account_id, up_to),
        )
        return [LockoutWindow.model_validate(dict(r)) for r in rows]

    # ------------------------------------------------------------------------------------------ decisions
    async def record_decision(self, decision: RiskDecision) -> None:
        """Persisted *before* anyone acts on it: a decision that is not on record does not exist."""
        await self._db.execute(
            "INSERT INTO risk_decisions (decision_id, intent_id, account_id, approved, approved_volume, symbol, side, "
            "reasons, decision, decided_at, expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (decision_id) DO NOTHING",
            (
                decision.decision_id,
                decision.intent_id,
                decision.account_id,
                decision.approved,
                decision.approved_volume,
                decision.symbol,
                decision.side.value if decision.side else None,
                jsonb(decision.reasons),
                jsonb(decision),
                decision.decided_at,
                decision.expires_at,
            ),
        )

    async def get_decision(self, decision_id: str) -> RiskDecision | None:
        row = await self._db.fetch_one("SELECT decision FROM risk_decisions WHERE decision_id = %s", (decision_id,))
        return RiskDecision.model_validate(row["decision"]) if row else None

    async def recent_decisions(self, account_id: str, limit: int = 50) -> list[RiskDecision]:
        rows = await self._db.fetch_all(
            "SELECT decision FROM risk_decisions WHERE account_id = %s ORDER BY decided_at DESC LIMIT %s",
            (account_id, max(1, min(limit, 500))),
        )
        return [RiskDecision.model_validate(r["decision"]) for r in rows]
