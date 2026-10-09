"""Migrations against a real PostgreSQL: they build the schema, are idempotent, recognise the existing database,
keep legacy rows, refuse an edited applied migration, and never put a secret in a column."""

from __future__ import annotations

import re

import psycopg
import pytest

from tests.support.postgres import Server, unique_name
from trading_os.infrastructure.database.migrate import (
    MigrationError,
    discover,
    discover_manual,
    migrate,
    run_manual,
    status,
)
from trading_os.infrastructure.database.pool import Database

pytestmark = pytest.mark.db

SECRETISH = re.compile(r"password|passwd|secret|token|api_?key|credential|private_?key", re.IGNORECASE)


async def test_every_migration_is_applied_to_an_empty_database(db: Database) -> None:
    rows = await db.fetch_all("SELECT version FROM schema_migrations ORDER BY version")
    assert [r["version"] for r in rows] == [m.version for m in discover()]
    tables = {
        r["table_name"]
        for r in await db.fetch_all("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    }
    assert {
        "candles", "ticks", "closed_trades", "position_opens", "risk_lockouts", "trade_captures", "news_releases",
        "setup_proposals", "accounts", "account_rule_versions", "execution_commands", "command_transitions",
        "events", "incidents", "risk_decisions", "trade_intents", "system_state", "schema_migrations",
    } <= tables  # fmt: skip


async def test_running_again_applies_nothing_and_reports_no_drift(fresh_database_url: str) -> None:
    assert await migrate(fresh_database_url) == []
    states = await status(fresh_database_url)
    assert states and all(s.applied and not s.drifted for s in states)


async def test_an_applied_migration_that_was_edited_is_refused(fresh_database_url: str) -> None:
    with psycopg.connect(fresh_database_url, autocommit=True) as conn:
        conn.execute("UPDATE schema_migrations SET checksum = 'not-the-real-checksum' WHERE version = '0002'")
    with pytest.raises(MigrationError, match="modified after it was applied"):
        await migrate(fresh_database_url)
    assert any(s.drifted for s in await status(fresh_database_url))


async def test_the_existing_database_is_recognised_and_its_legacy_rows_kept(pg_server: Server) -> None:
    """Simulate the production database: baseline tables with data, a legacy `execution_commands` row, no bookkeeping."""
    baseline = next(m for m in discover() if m.version == "0001")
    name = unique_name()
    url = pg_server.create_database(name)
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(baseline.sql)  # what the previous backend had created
            conn.execute(
                "INSERT INTO execution_commands (command_id, account_id, agent_id, risk_approval_id, symbol, side,"
                " order_type, volume, stop_loss, take_profit, issued_at, expires_at)"
                " VALUES ('cmd-legacy', '12345678', 'agent-1', 'risk-1', 'EURUSDm', 'BUY', 'MARKET', 0.01, 1.0, 1.2,"
                " now(), now())"
            )
            conn.execute(
                "INSERT INTO closed_trades VALUES ('12345678', 'p1', 'EURUSDm', 'buy', 0.01, -3.2, 1.1, now())"
            )
            conn.execute(
                "INSERT INTO risk_lockouts (lockout_id, account_id, reason, since) VALUES ('l1','12345678','x',now())"
            )
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(  # a capture the previous backend wrote, window and all
                "INSERT INTO trade_captures VALUES ('12345678', 'p1', 'entry', 'EURUSDm', 'M15', now() - interval '6 hours',"
                " now(), 1.1, 1.09, 1.12, NULL, now())"
            )
        applied = await migrate(url)
        assert applied == [m.version for m in discover()]
        with psycopg.connect(url) as conn:
            assert conn.execute(  # the old capture keeps everything it had, the window included
                "SELECT symbol, entry_price, stop_loss, timeframe IS NOT NULL, window_start_utc IS NOT NULL "
                "FROM trade_captures"
            ).fetchone() == ("EURUSDm", 1.1, 1.09, True, True)
            legacy = conn.execute("SELECT command_id, agent_id FROM legacy_execution_commands").fetchall()
            assert legacy == [("cmd-legacy", "agent-1")]
            columns = {r[0] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'execution_commands'"
            ).fetchall()}  # fmt: skip
            assert {"state", "fingerprint", "request"} <= columns and "risk_approval_id" not in columns
            assert conn.execute("SELECT count(*) FROM execution_commands").fetchone() == (0,)
            assert conn.execute("SELECT count(*) FROM closed_trades").fetchone() == (1,)  # untouched
            assert conn.execute("SELECT count(*) FROM risk_lockouts").fetchone() == (1,)
        assert await migrate(url) == []
    finally:
        pg_server.drop_database(name)


async def test_no_column_of_any_table_can_hold_a_secret(db: Database) -> None:
    rows = await db.fetch_all(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'"
    )
    offenders = [f"{r['table_name']}.{r['column_name']}" for r in rows if SECRETISH.search(r["column_name"])]
    assert offenders == []


async def test_a_destructive_script_is_manual_only(pg_server: Server) -> None:
    assert "drop_legacy_tables" in discover_manual()
    assert all(m.version != "drop_legacy_tables" for m in discover())  # the migrator never lists it
    name = unique_name()
    url = pg_server.create_database(name)
    try:
        await migrate(url)
        with psycopg.connect(url, autocommit=True) as conn:
            assert conn.execute("SELECT to_regclass('public.envelopes') IS NOT NULL").fetchone() == (True,)
        await migrate(url)  # migrating never drops it
        with psycopg.connect(url) as conn:
            assert conn.execute("SELECT to_regclass('public.envelopes') IS NOT NULL").fetchone() == (True,)
        await run_manual(url, "drop_legacy_tables")
        with psycopg.connect(url) as conn:
            assert conn.execute("SELECT to_regclass('public.envelopes') IS NULL").fetchone() == (True,)
        with pytest.raises(MigrationError):
            await run_manual(url, "does_not_exist")
    finally:
        pg_server.drop_database(name)


async def test_a_capture_is_data_only_and_the_chart_window_goes_only_by_a_manual_script(pg_server: Server) -> None:
    """ADR 0018: the graphic capture is gone. The window columns are optional (so a row is written without them), and removing
    them for good is a decision the user takes — the numbers stay either way."""
    assert "drop_capture_window" in discover_manual()
    assert all(m.name != "drop_capture_window" for m in discover())
    name = unique_name()
    url = pg_server.create_database(name)
    try:
        await migrate(url)
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(  # a row with no window at all: what the core writes now
                "INSERT INTO trade_captures (account_id, broker_position_id, kind, symbol, entry_price, stop_loss,"
                " take_profit, exit_price, captured_at) VALUES ('AC', 'p1', 'entry', 'EURUSDm', 1.1, 1.09, 1.12, NULL, now())"
            )
            assert conn.execute("SELECT count(*) FROM trade_captures").fetchone() == (1,)
        await run_manual(url, "drop_capture_window")
        with psycopg.connect(url) as conn:
            columns = {r[0] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'trade_captures'"
            ).fetchall()}  # fmt: skip
            assert not {"timeframe", "window_start_utc", "window_end_utc"} & columns
            assert {"symbol", "entry_price", "stop_loss", "take_profit", "exit_price", "captured_at"} <= columns
            assert conn.execute("SELECT symbol, entry_price FROM trade_captures").fetchone() == ("EURUSDm", 1.1)
        await run_manual(url, "drop_capture_window")  # idempotent
    finally:
        pg_server.drop_database(name)
