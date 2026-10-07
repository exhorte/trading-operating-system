"""Execution commands and what the agent reported about them.

The rule of this module: the command row is written **before** anything is sent, and every later change is an
optimistic compare-and-set on the previous state plus an appended ``command_transitions`` row, in one transaction.
Two writers can therefore never both move a command from the same state, and the history of a command can always
be replayed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from trading_os.domain.execution.commands import CommandState, ExecutionCommand, ExecutionRequest
from trading_os.domain.execution.records import AckRecord, ReconciliationRecord, ReportRecord
from trading_os.domain.execution.state import IN_DOUBT_STATES
from trading_os.infrastructure.database.pool import Database, Row, jsonb
from trading_os.shared.errors import Conflict

_COLUMNS = (
    "command_id, account_id, kind, symbol, side, state, route, mode, fingerprint, request, risk_decision_id, "
    "strategy_id, created_at, expires_at, sent_at, acknowledged_at, completed_at, attempts, detail, reject_code, "
    "broker_order_id, broker_position_id, filled_volume, average_price, broker_retcode"
)


def _to_command(row: Row) -> ExecutionCommand:
    return ExecutionCommand.model_validate(
        {
            "request": row["request"],
            "fingerprint": row["fingerprint"],
            "state": row["state"],
            "route": row["route"],
            "mode": row["mode"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "sent_at": row["sent_at"],
            "acknowledged_at": row["acknowledged_at"],
            "completed_at": row["completed_at"],
            "attempts": row["attempts"],
            "detail": row["detail"],
            "reject_code": row["reject_code"],
            "broker_order_id": row["broker_order_id"],
            "broker_position_id": row["broker_position_id"],
            "filled_volume": row["filled_volume"],
            "average_price": row["average_price"],
            "broker_retcode": row["broker_retcode"],
        }
    )


class ExecutionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------------------------------ commands
    async def insert(self, command: ExecutionCommand, at: datetime) -> bool:
        """Persist a new command. False when the id already exists (idempotency: the caller then reads the old one)."""
        request: ExecutionRequest = command.request
        async with self._db.transaction() as conn:
            cursor = await conn.execute(
                "INSERT INTO execution_commands (command_id, account_id, kind, symbol, side, state, route, mode, "
                "fingerprint, request, risk_decision_id, strategy_id, created_at, expires_at, sent_at, "
                "acknowledged_at, completed_at, attempts, detail, reject_code, broker_order_id, broker_position_id, "
                "filled_volume, average_price, broker_retcode, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s) ON CONFLICT (command_id) DO NOTHING",
                (
                    request.command_id,
                    request.account_id,
                    request.kind.value,
                    request.symbol,
                    request.side.value if request.side else None,
                    command.state.value,
                    command.route.value,
                    command.mode.value,
                    command.fingerprint,
                    jsonb(request),
                    request.risk_decision_id,
                    request.strategy_id,
                    command.created_at,
                    command.expires_at,
                    command.sent_at,
                    command.acknowledged_at,
                    command.completed_at,
                    command.attempts,
                    command.detail,
                    command.reject_code,
                    command.broker_order_id,
                    command.broker_position_id,
                    command.filled_volume,
                    command.average_price,
                    command.broker_retcode,
                    at,
                ),
            )
            if cursor.rowcount == 0:
                return False
            await conn.execute(
                "INSERT INTO command_transitions (command_id, from_state, to_state, event, at, detail) "
                "VALUES (%s, NULL, %s, 'CREATED', %s, %s)",
                (request.command_id, command.state.value, at, command.detail),
            )
        return True

    async def get(self, command_id: str) -> ExecutionCommand | None:
        row = await self._db.fetch_one(
            "SELECT " + _COLUMNS + " FROM execution_commands WHERE command_id = %s", (command_id,)
        )
        return _to_command(row) if row else None

    async def transition(self, previous: ExecutionCommand, updated: ExecutionCommand, event: str, at: datetime) -> None:
        """Compare-and-set from ``previous.state`` to ``updated.state``. Raises ``Conflict`` if another writer got
        there first — the caller re-reads and decides again; nothing is ever force-written."""
        async with self._db.transaction() as conn:
            cursor = await conn.execute(
                "UPDATE execution_commands SET state = %s, sent_at = %s, acknowledged_at = %s, completed_at = %s, "
                "attempts = %s, detail = %s, reject_code = %s, broker_order_id = %s, broker_position_id = %s, "
                "filled_volume = %s, average_price = %s, broker_retcode = %s, updated_at = %s "
                "WHERE command_id = %s AND state = %s",
                (
                    updated.state.value,
                    updated.sent_at,
                    updated.acknowledged_at,
                    updated.completed_at,
                    updated.attempts,
                    updated.detail,
                    updated.reject_code,
                    updated.broker_order_id,
                    updated.broker_position_id,
                    updated.filled_volume,
                    updated.average_price,
                    updated.broker_retcode,
                    at,
                    updated.command_id,
                    previous.state.value,
                ),
            )
            if cursor.rowcount == 0:
                raise Conflict(
                    f"command {updated.command_id} is no longer {previous.state.value}", code="command_state_changed"
                )
            await conn.execute(
                "INSERT INTO command_transitions (command_id, from_state, to_state, event, at, detail) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (updated.command_id, previous.state.value, updated.state.value, event, at, updated.detail),
            )

    async def recent(self, account_id: str | None, limit: int = 50) -> list[ExecutionCommand]:
        rows = await self._db.fetch_all(
            "SELECT " + _COLUMNS + " FROM execution_commands WHERE (%s::text IS NULL OR account_id = %s) "
            "ORDER BY created_at DESC LIMIT %s",
            (account_id, account_id, max(1, min(limit, 500))),
        )
        return [_to_command(r) for r in rows]

    async def in_states(self, states: Sequence[CommandState], account_id: str | None = None) -> list[ExecutionCommand]:
        rows = await self._db.fetch_all(
            "SELECT " + _COLUMNS + " FROM execution_commands WHERE state = ANY(%s) "
            "AND (%s::text IS NULL OR account_id = %s) ORDER BY created_at ASC",
            ([s.value for s in states], account_id, account_id),
        )
        return [_to_command(r) for r in rows]

    async def in_doubt(self, account_id: str | None = None) -> list[ExecutionCommand]:
        """Commands a broker order may exist for: a restart must never replay these."""
        return await self.in_states(sorted(IN_DOUBT_STATES, key=lambda s: s.value), account_id)

    async def transitions(self, command_id: str) -> list[Row]:
        return await self._db.fetch_all(
            "SELECT from_state, to_state, event, at, detail FROM command_transitions WHERE command_id = %s "
            "ORDER BY id ASC",
            (command_id,),
        )

    # ------------------------------------------------------------------------------------------ agent reports
    async def record_ack(self, ack: AckRecord) -> None:
        await self._db.execute(
            "INSERT INTO command_acks (command_id, agent_id, status, reason, received_at) VALUES (%s, %s, %s, %s, %s)",
            (ack.command_id, ack.agent_id, ack.status, ack.reason, ack.received_at),
        )

    async def record_report(self, report: ReportRecord) -> None:
        await self._db.execute(
            "INSERT INTO execution_reports (report_id, command_id, account_id, agent_id, symbol, side, status, "
            "detail, reported_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (report_id) DO NOTHING",
            (
                report.report_id,
                report.command_id,
                report.account_id,
                report.agent_id,
                report.symbol,
                report.side,
                report.status,
                report.detail,
                report.reported_at,
            ),
        )

    async def upsert_reconciliation(self, record: ReconciliationRecord) -> None:
        """Current-state projection of what the agent knows about a command it once left UNKNOWN."""
        await self._db.execute(
            "INSERT INTO command_reconciliations (command_id, account_id, outcome, symbol, side, broker_order_id, "
            "broker_position_id, filled_volume, average_price, broker_retcode, attempts, detail, reconciled_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (command_id) DO UPDATE SET "
            "outcome = EXCLUDED.outcome, symbol = EXCLUDED.symbol, side = EXCLUDED.side, "
            "broker_order_id = EXCLUDED.broker_order_id, broker_position_id = EXCLUDED.broker_position_id, "
            "filled_volume = EXCLUDED.filled_volume, average_price = EXCLUDED.average_price, "
            "broker_retcode = EXCLUDED.broker_retcode, attempts = EXCLUDED.attempts, detail = EXCLUDED.detail, "
            "reconciled_at = EXCLUDED.reconciled_at",
            (
                record.command_id,
                record.account_id,
                record.outcome,
                record.symbol,
                record.side,
                record.broker_order_id,
                record.broker_position_id,
                record.filled_volume,
                record.average_price,
                record.broker_retcode,
                record.attempts,
                record.detail,
                record.reconciled_at,
            ),
        )

    async def reconciliations(self, account_id: str) -> list[ReconciliationRecord]:
        rows = await self._db.fetch_all(
            "SELECT command_id, account_id, outcome, symbol, side, broker_order_id, broker_position_id, "
            "filled_volume, average_price, broker_retcode, attempts, detail, reconciled_at "
            "FROM command_reconciliations WHERE account_id = %s ORDER BY reconciled_at DESC",
            (account_id,),
        )
        return [ReconciliationRecord.model_validate(dict(r)) for r in rows]
