"""Accounts and their versioned rules. No secret passes through here: an ``Account`` has no field for one."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg.errors

from trading_os.domain.accounts.anti_tilt import SessionFact
from trading_os.domain.accounts.models import Account
from trading_os.domain.accounts.rules_ledger import CancelOutcome, RuleVersion, cancel_outcome
from trading_os.infrastructure.database.pool import Database, Row, jsonb
from trading_os.shared.errors import Conflict, NotFound

_COLUMNS = (
    "account_id, name, provider, platform, account_type, login, server, currency, environment, terminal_path, "
    "symbol_suffix, trading_enabled, risk_profile, trading_rules, execution_profile, created_at"
)


def _to_account(row: Row) -> Account:
    return Account.model_validate(
        {
            "id": row["account_id"],
            "name": row["name"],
            "provider": row["provider"],
            "platform": row["platform"],
            "account_type": row["account_type"],
            "login": row["login"],
            "server": row["server"],
            "currency": row["currency"],
            "environment": row["environment"],
            "terminal_path": row["terminal_path"],
            "symbol_suffix": row["symbol_suffix"],
            "trading_enabled": row["trading_enabled"],
            "risk_profile": row["risk_profile"],
            "trading_rules": row["trading_rules"],
            "execution_profile": row["execution_profile"],
            "created_at": row["created_at"],
        }
    )


class AccountRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def all(self) -> list[Account]:
        rows = await self._db.fetch_all(
            "SELECT " + _COLUMNS + " FROM accounts WHERE archived_at IS NULL ORDER BY created_at, account_id"
        )
        return [_to_account(r) for r in rows]

    async def get(self, account_id: str) -> Account | None:
        row = await self._db.fetch_one(
            "SELECT " + _COLUMNS + " FROM accounts WHERE account_id = %s AND archived_at IS NULL", (account_id,)
        )
        return _to_account(row) if row else None

    async def require(self, account_id: str) -> Account:
        account = await self.get(account_id)
        if account is None:
            raise NotFound(f"unknown account {account_id!r}", code="account_not_found")
        return account

    async def insert(self, account: Account) -> None:
        try:
            await self._db.execute(
                "INSERT INTO accounts (" + _COLUMNS + ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s)",
                (
                    account.id,
                    account.name,
                    account.provider.value,
                    account.platform.value,
                    account.account_type.value,
                    account.login,
                    account.server,
                    account.currency,
                    account.environment.value,
                    account.terminal_path,
                    account.symbol_suffix,
                    account.trading_enabled,
                    jsonb(account.risk_profile),
                    jsonb(account.trading_rules),
                    jsonb(account.execution_profile),
                    account.created_at,
                ),
            )
        except psycopg.errors.UniqueViolation as error:
            raise Conflict(
                f"account {account.id!r} or login {account.login} on {account.server!r} already exists",
                code="account_exists",
            ) from error

    async def update_details(
        self, account_id: str, *, name: str | None, terminal_path: str | None, symbol_suffix: str | None
    ) -> None:
        updated = await self._db.execute(
            "UPDATE accounts SET name = coalesce(%s, name), terminal_path = coalesce(%s, terminal_path), "
            "symbol_suffix = coalesce(%s, symbol_suffix) WHERE account_id = %s AND archived_at IS NULL",
            (name, terminal_path, symbol_suffix, account_id),
        )
        if updated == 0:
            raise NotFound(f"unknown account {account_id!r}", code="account_not_found")

    async def set_trading_enabled(self, account_id: str, enabled: bool) -> None:
        updated = await self._db.execute(
            "UPDATE accounts SET trading_enabled = %s WHERE account_id = %s AND archived_at IS NULL",
            (enabled, account_id),
        )
        if updated == 0:
            raise NotFound(f"unknown account {account_id!r}", code="account_not_found")

    async def archive(self, account_id: str, at: datetime) -> None:
        updated = await self._db.execute(
            "UPDATE accounts SET archived_at = %s WHERE account_id = %s AND archived_at IS NULL", (at, account_id)
        )
        if updated == 0:
            raise NotFound(f"unknown account {account_id!r}", code="account_not_found")


_VERSION_COLUMNS = (
    "v.version_id, v.account_id, v.rules, v.requested_at, v.deferred, v.deferral_reasons, v.cancelled_at, "
    "EXISTS (SELECT 1 FROM trading_day_anchors a WHERE a.starts_at_utc > v.requested_at) AS day_started_since"
)


def _to_version(row: Row) -> RuleVersion:
    return RuleVersion.model_validate(
        {
            "version_id": row["version_id"],
            "account_id": row["account_id"],
            "rules": row["rules"],
            "requested_at": row["requested_at"],
            "deferred": row["deferred"],
            "deferral_reasons": row["deferral_reasons"],
            "cancelled_at": row["cancelled_at"],
            "day_started_since": row["day_started_since"],
        }
    )


class RuleVersionRepository:
    MAX_VERSIONS = 200

    def __init__(self, db: Database) -> None:
        self._db = db

    async def for_account(self, account_id: str) -> list[RuleVersion]:
        rows = await self._db.fetch_all(
            "SELECT " + _VERSION_COLUMNS + " FROM account_rule_versions v WHERE v.account_id = %s "
            "ORDER BY v.requested_at DESC LIMIT %s",
            (account_id, self.MAX_VERSIONS),
        )
        return [_to_version(r) for r in rows]

    async def get(self, version_id: str) -> RuleVersion | None:
        row = await self._db.fetch_one(
            "SELECT " + _VERSION_COLUMNS + " FROM account_rule_versions v WHERE v.version_id = %s", (version_id,)
        )
        return _to_version(row) if row else None

    async def append(self, version: RuleVersion) -> RuleVersion:
        """Append-only: a change is a new row. A just-written row cannot have an anchor after it."""
        await self._db.execute(
            "INSERT INTO account_rule_versions (version_id, account_id, rules, requested_at, deferred, "
            "deferral_reasons) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                version.version_id,
                version.account_id,
                jsonb(version.rules),
                version.requested_at,
                version.deferred,
                jsonb(version.deferral_reasons),
            ),
        )
        return version.model_copy(update={"day_started_since": False})

    async def try_cancel(self, version_id: str, at: datetime) -> CancelOutcome:
        outcome = cancel_outcome(await self.get(version_id))
        if outcome is not CancelOutcome.CANCELLED:
            return outcome
        # The same conditions in the UPDATE itself: an anchor resolved between the read and the write must still win.
        updated = await self._db.execute(
            "UPDATE account_rule_versions SET cancelled_at = %s WHERE version_id = %s AND deferred "
            "AND cancelled_at IS NULL AND NOT EXISTS (SELECT 1 FROM trading_day_anchors a "
            "WHERE a.starts_at_utc > account_rule_versions.requested_at)",
            (at, version_id),
        )
        return CancelOutcome.CANCELLED if updated == 1 else CancelOutcome.ALREADY_IN_EFFECT

    async def session_facts(self, now: datetime) -> list[SessionFact]:
        """Every account whose trading day is in progress (latest anchor under 25 h old) or locked right now."""
        rows = await self._db.fetch_all(
            """
            WITH latest AS (
                SELECT DISTINCT ON (account_id) account_id, starts_at_utc
                FROM trading_day_anchors
                ORDER BY account_id, starts_at_utc DESC
            ),
            in_progress AS (
                SELECT l.account_id, l.starts_at_utc,
                       (SELECT count(*) FROM position_opens p
                        WHERE p.account_id = l.account_id AND p.opened_at >= l.starts_at_utc)::int AS trades_today
                FROM latest l
                WHERE l.starts_at_utc > %s::timestamptz - interval '25 hours'
            ),
            locked AS (
                SELECT DISTINCT ON (account_id) account_id, reason
                FROM risk_lockouts
                WHERE cleared_at IS NULL AND (until IS NULL OR until > %s::timestamptz)
                ORDER BY account_id, since DESC
            )
            SELECT coalesce(i.account_id, k.account_id) AS account_id,
                   i.starts_at_utc AS day_anchor_starts_at_utc,
                   coalesce(i.trades_today, 0) AS trades_today,
                   k.reason AS active_lockout_reason
            FROM in_progress i
            FULL OUTER JOIN locked k ON k.account_id = i.account_id
            ORDER BY 1
            """,
            (now, now),
        )
        return [SessionFact.model_validate(dict(r)) for r in rows]


class SystemStateRepository:
    """Small durable facts under a string key: the active account, the autonomy state and lease, the last news sync."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, key: str) -> Any | None:
        row = await self._db.fetch_one("SELECT value FROM system_state WHERE key = %s", (key,))
        return row["value"] if row else None

    async def set(self, key: str, value: Any) -> None:
        await self._db.execute(
            "INSERT INTO system_state (key, value, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
            (key, jsonb(value)),
        )

    async def delete(self, key: str) -> None:
        await self._db.execute("DELETE FROM system_state WHERE key = %s", (key,))
