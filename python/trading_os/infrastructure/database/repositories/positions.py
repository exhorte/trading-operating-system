"""Position history: every position opened, every position closed, the agent's scan, and the immutable T05 captures."""

from __future__ import annotations

from datetime import datetime, timedelta

from trading_os.domain.execution.records import PositionScanRecord
from trading_os.domain.journal.models import JournalTrade, TradeCapture
from trading_os.domain.positions.models import ClosedTrade
from trading_os.infrastructure.database.pool import Database, Row

# How far before the entry the capture window starts (what the cockpit may draw, never wider).
CAPTURE_LOOKBACK = timedelta(hours=6)


def _to_closed(row: Row, account_id: str) -> ClosedTrade:
    return ClosedTrade(
        account_id=account_id,
        broker_position_id=row["broker_position_id"],
        symbol=row["symbol"],
        side=row["side"],
        volume=row["volume"],
        realized_pnl=row["realized_pnl"],
        exit_price=row["exit_price"],
        closed_at=row["closed_at"],
    )


def _to_capture(row: Row) -> TradeCapture:
    return TradeCapture.model_validate(dict(row))


class PositionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------------------------------ opens / closes
    async def record_open(self, account_id: str, broker_position_id: str, opened_at: datetime) -> bool:
        """True when this is the first time the position is seen (the trade counts once)."""
        inserted = await self._db.execute(
            "INSERT INTO position_opens (account_id, broker_position_id, opened_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (account_id, broker_position_id) DO NOTHING",
            (account_id, broker_position_id, opened_at),
        )
        return inserted == 1

    async def record_closed(self, trade: ClosedTrade) -> bool:
        inserted = await self._db.execute(
            "INSERT INTO closed_trades (account_id, broker_position_id, symbol, side, volume, realized_pnl, "
            "exit_price, closed_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (account_id, broker_position_id) DO NOTHING",
            (
                trade.account_id,
                trade.broker_position_id,
                trade.symbol,
                trade.side.value,
                trade.volume,
                trade.realized_pnl,
                trade.exit_price,
                trade.closed_at,
            ),
        )
        return inserted == 1

    async def known_open_ids(self, account_id: str) -> set[str]:
        rows = await self._db.fetch_all(
            "SELECT broker_position_id FROM position_opens WHERE account_id = %s "
            "AND broker_position_id NOT IN (SELECT broker_position_id FROM closed_trades WHERE account_id = %s)",
            (account_id, account_id),
        )
        return {r["broker_position_id"] for r in rows}

    async def closed_between(self, account_id: str, start: datetime, end: datetime) -> list[ClosedTrade]:
        rows = await self._db.fetch_all(
            "SELECT broker_position_id, symbol, side, volume, realized_pnl, exit_price, closed_at FROM closed_trades "
            "WHERE account_id = %s AND closed_at >= %s AND closed_at <= %s ORDER BY closed_at ASC",
            (account_id, start, end),
        )
        return [_to_closed(r, account_id) for r in rows]

    async def opens_between(self, account_id: str, start: datetime, end: datetime) -> list[tuple[str, datetime]]:
        rows = await self._db.fetch_all(
            "SELECT broker_position_id, opened_at FROM position_opens WHERE account_id = %s "
            "AND opened_at >= %s AND opened_at <= %s ORDER BY opened_at ASC",
            (account_id, start, end),
        )
        return [(r["broker_position_id"], r["opened_at"]) for r in rows]

    # ------------------------------------------------------------------------------------------ journal
    async def journal_trades(self, account_id: str, start: datetime, end: datetime) -> list[JournalTrade]:
        rows = await self._db.fetch_all(
            """
            SELECT ct.broker_position_id, ct.symbol, ct.side, ct.volume, tc.entry_price, ct.exit_price,
                   ct.realized_pnl, tc.stop_loss, po.opened_at, ct.closed_at,
                   (tc.broker_position_id IS NOT NULL) AS has_capture
            FROM closed_trades ct
            LEFT JOIN position_opens po
              ON po.account_id = ct.account_id AND po.broker_position_id = ct.broker_position_id
            LEFT JOIN trade_captures tc
              ON tc.account_id = ct.account_id AND tc.broker_position_id = ct.broker_position_id AND tc.kind = 'entry'
            WHERE ct.account_id = %s AND ct.closed_at >= %s AND ct.closed_at <= %s
            ORDER BY ct.closed_at DESC
            """,
            (account_id, start, end),
        )
        return [JournalTrade.model_validate(dict(r)) for r in rows]

    # ------------------------------------------------------------------------------------------ captures (T05)
    async def record_capture_entry(
        self,
        account_id: str,
        broker_position_id: str,
        symbol: str,
        timeframe: str,
        opened_at: datetime,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> None:
        """Immutable: written once per position and kind, at the moment of the real event, never updated."""
        await self._db.execute(
            "INSERT INTO trade_captures (account_id, broker_position_id, kind, symbol, timeframe, window_start_utc, "
            "window_end_utc, entry_price, stop_loss, take_profit, exit_price, captured_at) "
            "VALUES (%s, %s, 'entry', %s, %s, %s, %s, %s, %s, %s, NULL, %s) "
            "ON CONFLICT (account_id, broker_position_id, kind) DO NOTHING",
            (
                account_id,
                broker_position_id,
                symbol,
                timeframe,
                opened_at - CAPTURE_LOOKBACK,
                opened_at,
                entry_price,
                stop_loss,
                take_profit,
                opened_at,
            ),
        )

    async def record_capture_exit(
        self, account_id: str, broker_position_id: str, exit_price: float, closed_at: datetime
    ) -> bool:
        """The exit row copies symbol, timeframe, window start and the planned levels from the entry row, so a viewer
        needs one row per kind and never a join. False when there is no entry to copy (nothing is invented)."""
        inserted = await self._db.execute(
            "INSERT INTO trade_captures (account_id, broker_position_id, kind, symbol, timeframe, window_start_utc, "
            "window_end_utc, entry_price, stop_loss, take_profit, exit_price, captured_at) "
            "SELECT account_id, broker_position_id, 'exit', symbol, timeframe, window_start_utc, %s, entry_price, "
            "stop_loss, take_profit, %s, %s FROM trade_captures "
            "WHERE account_id = %s AND broker_position_id = %s AND kind = 'entry' "
            "ON CONFLICT (account_id, broker_position_id, kind) DO NOTHING",
            (closed_at, exit_price, closed_at, account_id, broker_position_id),
        )
        return inserted == 1

    async def captures(
        self, account_id: str, broker_position_id: str
    ) -> tuple[TradeCapture | None, TradeCapture | None]:
        rows = await self._db.fetch_all(
            "SELECT account_id, broker_position_id, kind, symbol, timeframe, window_start_utc, window_end_utc, "
            "entry_price, stop_loss, take_profit, exit_price, captured_at FROM trade_captures "
            "WHERE account_id = %s AND broker_position_id = %s",
            (account_id, broker_position_id),
        )
        captures = [_to_capture(r) for r in rows]
        return (
            next((c for c in captures if c.kind == "entry"), None),
            next((c for c in captures if c.kind == "exit"), None),
        )

    # ------------------------------------------------------------------------------------------ agent scan (EA-06)
    async def upsert_scan(self, scan: PositionScanRecord) -> None:
        """Current-state projection, not a log: one row per (account, position), refreshed on every scan."""
        await self._db.execute(
            "INSERT INTO position_scans (account_id, broker_position_id, symbol, side, volume, magic_number, "
            "is_external, known_command_id, scanned_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (account_id, broker_position_id) DO UPDATE SET symbol = EXCLUDED.symbol, "
            "side = EXCLUDED.side, volume = EXCLUDED.volume, magic_number = EXCLUDED.magic_number, "
            "is_external = EXCLUDED.is_external, known_command_id = EXCLUDED.known_command_id, "
            "scanned_at = EXCLUDED.scanned_at",
            (
                scan.account_id,
                scan.broker_position_id,
                scan.symbol,
                scan.side,
                scan.volume,
                scan.magic_number,
                scan.is_external,
                scan.known_command_id,
                scan.scanned_at,
            ),
        )

    async def external_positions(self, account_id: str) -> list[PositionScanRecord]:
        rows = await self._db.fetch_all(
            "SELECT account_id, broker_position_id, symbol, side, volume, magic_number, is_external, "
            "known_command_id, scanned_at FROM position_scans WHERE account_id = %s AND is_external "
            "ORDER BY scanned_at DESC",
            (account_id,),
        )
        return [PositionScanRecord.model_validate(dict(r)) for r in rows]
