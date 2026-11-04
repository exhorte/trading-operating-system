"""The provider's loss references: one balance per account and per provider day, written once (migration 0006, ADR 0036).

There is no update and no delete here, on purpose: a reference that could be rewritten would let a restart, a reconnection or a change
of settings reset a limit. ``record`` keeps the first value written for a day and says whether it was the one stored.
"""

from __future__ import annotations

from datetime import date

from trading_os.domain.providers.loss_floors import LossReference
from trading_os.infrastructure.database.pool import Database, Row


def _to_reference(row: Row) -> LossReference:
    return LossReference(
        local_date=row["local_date"],
        timezone=row["timezone"],
        reference_balance=row["reference_balance"],
        recorded_at=row["recorded_at"],
        source=row["source"],
        rule_set_id=row["rule_set_id"],
    )


class ProviderRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(self, account_id: str, reference: LossReference) -> bool:
        """Store ``reference`` unless that day already has one. ``True`` = this call wrote it."""
        written = await self._db.execute(
            "INSERT INTO provider_loss_references "
            "(account_id, local_date, timezone, reference_balance, recorded_at, source, rule_set_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (account_id, local_date) DO NOTHING",
            (
                account_id,
                reference.local_date,
                reference.timezone,
                reference.reference_balance,
                reference.recorded_at,
                reference.source,
                reference.rule_set_id,
            ),
        )
        return written == 1

    async def record_many(self, account_id: str, references: list[LossReference]) -> int:
        written = 0
        for reference in references:
            written += await self.record(account_id, reference)
        return written

    async def get(self, account_id: str, day: date) -> LossReference | None:
        row = await self._db.fetch_one(
            "SELECT * FROM provider_loss_references WHERE account_id = %s AND local_date = %s", (account_id, day)
        )
        return _to_reference(row) if row else None

    async def all(self, account_id: str) -> list[LossReference]:
        rows = await self._db.fetch_all(
            "SELECT * FROM provider_loss_references WHERE account_id = %s ORDER BY local_date", (account_id,)
        )
        return [_to_reference(row) for row in rows]
