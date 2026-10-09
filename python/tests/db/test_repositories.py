"""The repositories against a real PostgreSQL: SQL that is only ever executed by a database is only ever tested by one."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.support.builders import (
    NOW,
    make_account,
    make_command,
    make_decision,
    make_intent,
    make_rule_version,
)
from trading_os.domain.accounts.models import Environment
from trading_os.domain.accounts.rules_ledger import CancelOutcome
from trading_os.domain.events import AccountConnected, LockoutEnabled
from trading_os.domain.execution.commands import CommandState
from trading_os.domain.execution.records import AckRecord, PositionScanRecord, ReconciliationRecord, ReportRecord
from trading_os.domain.journal.models import TradeCapture
from trading_os.domain.market.calendar import UpcomingRelease
from trading_os.domain.market.models import Candle, Tick
from trading_os.domain.positions.models import ClosedTrade
from trading_os.domain.primitives import Side, Timeframe
from trading_os.domain.strategy.evaluation import StrategyEvaluation
from trading_os.domain.system.incidents import Incident
from trading_os.domain.system.supervision import Severity
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.shared.errors import Conflict, NotFound, Unavailable

pytestmark = pytest.mark.db


@pytest.fixture
async def repos(db: Database) -> Repositories:
    return Repositories.create(db)


def at(**delta: float) -> datetime:
    return NOW + timedelta(**delta)


# ------------------------------------------------------------------------------------------------------ database


async def test_an_unreachable_database_fails_closed_with_a_typed_error() -> None:
    database = Database("postgresql://nobody@127.0.0.1:1/none", min_size=1, max_size=1, connect_timeout=1)
    await database.open()
    try:
        with pytest.raises(Unavailable) as caught:
            await database.fetch_value("SELECT 1")
        assert caught.value.code == "database_unavailable"
        assert database.health.up is False and database.health.last_error
        assert await database.ping() is False
    finally:
        await database.close()


async def test_a_closed_database_refuses_instead_of_hanging() -> None:
    database = Database("postgresql://nobody@127.0.0.1:1/none")
    with pytest.raises(Unavailable):
        await database.fetch_value("SELECT 1")


async def test_the_session_runs_in_utc_and_returns_aware_datetimes(db: Database) -> None:
    value = await db.fetch_value("SELECT now()")
    assert value.tzinfo is not None and value.utcoffset() == timedelta(0)
    assert await db.ping() is True and db.health.up


# ------------------------------------------------------------------------------------------------------ accounts


async def test_an_account_round_trips_with_its_rules_and_never_a_secret(repos: Repositories) -> None:
    account = make_account("EXN-1", login=1000001)
    await repos.accounts.insert(account)
    stored = await repos.accounts.get("EXN-1")
    assert stored == account
    assert [a.id for a in await repos.accounts.all()] == ["EXN-1"]


async def test_the_same_broker_login_cannot_be_registered_twice(repos: Repositories) -> None:
    await repos.accounts.insert(make_account("AC1", login=555))
    with pytest.raises(Conflict) as caught:
        await repos.accounts.insert(make_account("AC2", login=555))
    assert caught.value.code == "account_exists"
    with pytest.raises(Conflict):
        await repos.accounts.insert(make_account("AC1", login=556))


async def test_trading_can_be_disabled_and_an_account_archived(repos: Repositories) -> None:
    await repos.accounts.insert(make_account("AC1", login=1))
    await repos.accounts.set_trading_enabled("AC1", False)
    assert (await repos.accounts.require("AC1")).trading_enabled is False
    await repos.accounts.update_details("AC1", name="Renamed", terminal_path=None, symbol_suffix=None)
    assert (await repos.accounts.require("AC1")).name == "Renamed"
    await repos.accounts.archive("AC1", NOW)
    assert await repos.accounts.get("AC1") is None
    with pytest.raises(NotFound):
        await repos.accounts.require("AC1")
    await repos.accounts.insert(make_account("AC3", login=1))  # the login is free again once archived


async def test_rule_versions_are_append_only_and_cancellation_follows_the_anchor(repos: Repositories) -> None:
    await repos.accounts.insert(make_account("AC1", login=1))
    immediate = make_rule_version("AC1", requested_at=at(hours=-5), deferred=False)
    deferred = make_rule_version("AC1", requested_at=at(hours=-1), deferred=True)
    await repos.rules.append(immediate)
    await repos.rules.append(deferred)
    versions = await repos.rules.for_account("AC1")
    assert [v.version_id for v in versions] == [deferred.version_id, immediate.version_id]  # newest first
    assert all(not v.day_started_since for v in versions)

    assert await repos.rules.try_cancel("nope", NOW) is CancelOutcome.NOT_FOUND
    assert await repos.rules.try_cancel(immediate.version_id, NOW) is CancelOutcome.NOT_DEFERRED

    await repos.risk.record_anchor("AC1", at(minutes=-30))  # a trading day started after the deferred request
    assert (await repos.rules.get(deferred.version_id)).day_started_since is True  # type: ignore[union-attr]
    assert await repos.rules.try_cancel(deferred.version_id, NOW) is CancelOutcome.ALREADY_IN_EFFECT

    other = make_rule_version("AC1", requested_at=at(minutes=-10), deferred=True)
    await repos.rules.append(other)
    assert await repos.rules.try_cancel(other.version_id, NOW) is CancelOutcome.CANCELLED
    assert await repos.rules.try_cancel(other.version_id, NOW) is CancelOutcome.ALREADY_CANCELLED


async def test_session_facts_report_accounts_in_session_or_locked(repos: Repositories, db: Database) -> None:
    now = datetime.now(UTC)
    await repos.risk.record_anchor("AC1", now - timedelta(hours=3))
    await repos.positions.record_open("AC1", "p1", now - timedelta(hours=2))
    await repos.positions.record_open("AC1", "p2", now - timedelta(hours=1))
    await repos.risk.record_anchor("OLD", now - timedelta(hours=40))  # day over: not a session in progress
    await repos.risk.open_lockout("lk1", "AC2", "Kill switch manuel", now - timedelta(minutes=5), None)
    facts = {f.account_id: f for f in await repos.rules.session_facts(now)}
    assert set(facts) == {"AC1", "AC2"}
    assert facts["AC1"].trades_today == 2 and facts["AC1"].active_lockout_reason is None
    assert facts["AC2"].active_lockout_reason == "Kill switch manuel" and facts["AC2"].trades_today == 0


async def test_system_state_stores_json_and_overwrites(repos: Repositories) -> None:
    assert await repos.state.get("active_account") is None
    await repos.state.set("active_account", {"id": "AC1", "since": "2026-10-07T12:00:00Z"})
    await repos.state.set("active_account", {"id": "AC2"})
    assert await repos.state.get("active_account") == {"id": "AC2"}
    await repos.state.delete("active_account")
    assert await repos.state.get("active_account") is None


# ------------------------------------------------------------------------------------------------------ risk


async def test_the_trading_day_counts_opens_since_the_anchor_and_the_streak_across_midnight(
    repos: Repositories,
) -> None:
    anchor = at(hours=-6)
    await repos.risk.record_anchor("AC1", anchor)
    await repos.risk.record_anchor("AC1", anchor)  # idempotent
    assert (await repos.risk.today("AC1", NOW)).day_start_equity is None  # unknown, never zero
    assert await repos.risk.confirm_day_start_equity("AC1", anchor, 10_000.0) is True
    assert await repos.risk.confirm_day_start_equity("AC1", anchor, 9_000.0) is False  # never overwritten

    assert await repos.positions.record_open("AC1", "p0", anchor - timedelta(hours=1)) is True  # before the anchor
    assert await repos.positions.record_open("AC1", "p1", anchor + timedelta(hours=1)) is True
    assert await repos.positions.record_open("AC1", "p1", anchor + timedelta(hours=1)) is False  # counts once
    assert await repos.positions.record_open("AC1", "p2", anchor + timedelta(hours=2)) is True

    for i, (pnl, hours) in enumerate([(5.0, -30), (-1.0, -10), (-2.0, -5), (-3.0, -1)]):
        trade = ClosedTrade(
            account_id="AC1",
            broker_position_id=f"c{i}",
            symbol="EURUSDm",
            side=Side.BUY,
            volume=0.01,
            realized_pnl=pnl,
            exit_price=1.1,
            closed_at=at(hours=hours),
        )
        assert await repos.positions.record_closed(trade) is True
        assert await repos.positions.record_closed(trade) is False

    today = await repos.risk.today("AC1", NOW)
    assert today.day_anchor_starts_at_utc == anchor and today.day_start_equity == 10_000.0
    assert today.trades_today == 2
    assert today.consecutive_losses == 3  # the streak spans the day anchor
    assert today.last_loss_at == at(hours=-1)
    assert today.active_lockout is None


async def test_a_lockout_is_opened_once_cleared_by_stamping_and_expires_when_timed(
    repos: Repositories, db: Database
) -> None:
    now = datetime.now(UTC)
    await repos.risk.open_lockout(
        "lk1", "AC1", "Pertes consécutives", now - timedelta(minutes=40), now - timedelta(minutes=10)
    )
    assert await repos.risk.active_lockout("AC1", now) is None  # the timed pause already ran out

    await repos.risk.open_lockout("lk2", "AC1", "Kill switch manuel", now - timedelta(minutes=5), None)
    await repos.risk.open_lockout("lk2", "AC1", "again", now, None)  # idempotent on the id
    active = await repos.risk.active_lockout("AC1", now)
    assert active is not None and active.lockout_id == "lk2" and active.reason == "Kill switch manuel"
    assert (await repos.risk.today("AC1", now)).active_lockout == active

    await repos.risk.acknowledge("AC1", "lk2", now)
    await repos.risk.acknowledge("AC1", "lk2", now)
    assert await repos.risk.clear_lockout("AC1", "kill-switch-ack", now) == "lk2"
    assert await repos.risk.active_lockout("AC1", now) is None
    assert await repos.risk.clear_lockout("AC1", "manual", now) is None

    stamps = await db.fetch_all("SELECT lockout_id, cleared_by FROM risk_lockouts ORDER BY since")
    assert [(r["lockout_id"], r["cleared_by"]) for r in stamps] == [
        ("lk1", "pause-expired"),
        ("lk2", "kill-switch-ack"),
    ]
    history = await repos.risk.lockout_history("AC1", now)
    assert [h.lockout_id for h in history] == ["lk1", "lk2"] and history[1].cleared_at is not None


async def test_a_risk_decision_is_persisted_and_read_back_whole(repos: Repositories) -> None:
    decision = make_decision("AC1", approved=False, reasons=["news_restriction", "spread_too_wide"])
    await repos.risk.record_decision(decision)
    await repos.risk.record_decision(decision)  # idempotent
    assert await repos.risk.get_decision(decision.decision_id) == decision
    assert await repos.risk.recent_decisions("AC1") == [decision]
    assert await repos.risk.get_decision("missing") is None


# ------------------------------------------------------------------------------------------------------ positions


async def test_captures_are_immutable_and_the_exit_copies_the_entry(repos: Repositories) -> None:
    opened, closed = at(hours=-3), at(hours=-1)
    assert await repos.positions.record_capture_exit("AC1", "p1", 1.2, closed) is False  # no entry: nothing invented
    await repos.positions.record_capture_entry("AC1", "p1", "EURUSDm", opened, 1.1, 1.09, 1.12)
    await repos.positions.record_capture_entry("AC1", "p1", "EURUSDm", opened, 9.9, 9.9, 9.9)  # ignored
    assert await repos.positions.record_capture_exit("AC1", "p1", 1.115, closed) is True
    assert await repos.positions.record_capture_exit("AC1", "p1", 7.7, closed) is False
    entry, exit_ = await repos.positions.captures("AC1", "p1")
    assert isinstance(entry, TradeCapture) and isinstance(exit_, TradeCapture)
    assert entry.entry_price == 1.1 and entry.exit_price is None
    assert entry.captured_at == opened and exit_.captured_at == closed
    assert exit_.exit_price == 1.115 and exit_.entry_price == 1.1 and exit_.stop_loss == 1.09


async def test_the_journal_joins_closed_trades_with_their_opening_and_capture(repos: Repositories) -> None:
    await repos.positions.record_open("AC1", "p1", at(hours=-3))
    await repos.positions.record_capture_entry("AC1", "p1", "EURUSDm", at(hours=-3), 1.1, 1.09, 1.12)
    await repos.positions.record_closed(
        ClosedTrade(
            account_id="AC1",
            broker_position_id="p1",
            symbol="EURUSDm",
            side=Side.SELL,
            volume=0.02,
            realized_pnl=-4.0,
            exit_price=1.095,
            closed_at=at(hours=-1),
        )
    )
    await repos.positions.record_closed(
        ClosedTrade(
            account_id="AC1",
            broker_position_id="p2",
            symbol="XAUUSDm",
            side=Side.BUY,
            volume=0.01,
            realized_pnl=7.5,
            exit_price=3300.0,
            closed_at=at(hours=-2),
        )
    )  # a trade we never saw open (missed round trip)
    trades = await repos.positions.journal_trades("AC1", at(days=-1), NOW)
    assert [t.broker_position_id for t in trades] == ["p1", "p2"]  # newest first
    p1, p2 = trades
    assert p1.has_capture and p1.entry_price == 1.1 and p1.stop_loss == 1.09 and p1.opened_at == at(hours=-3)
    assert not p2.has_capture and p2.entry_price is None and p2.opened_at is None
    assert await repos.positions.known_open_ids("AC1") == set()


async def test_the_agents_scan_is_a_current_state_projection(repos: Repositories) -> None:
    def scan(external: bool, volume: float) -> PositionScanRecord:
        return PositionScanRecord(
            account_id="AC1",
            broker_position_id="p9",
            symbol="EURUSDm",
            side="BUY",
            volume=volume,
            magic_number=0 if external else 77,
            is_external=external,
            scanned_at=NOW,
        )

    await repos.positions.upsert_scan(scan(True, 0.1))
    await repos.positions.upsert_scan(scan(True, 0.3))
    external = await repos.positions.external_positions("AC1")
    assert len(external) == 1 and external[0].volume == 0.3
    await repos.positions.upsert_scan(scan(False, 0.3))  # it turned out to be ours
    assert await repos.positions.external_positions("AC1") == []


# ------------------------------------------------------------------------------------------------------ market


def candle(minutes: int, close: float = 1.1, closed: bool = True) -> Candle:
    return Candle(
        symbol="EURUSDm",
        timeframe=Timeframe.M1,
        open_time=at(minutes=minutes),
        open=1.0,
        high=1.2,
        low=0.9,
        close=close,
        volume=10,
        closed=closed,
    )


async def test_candles_are_upserted_and_read_back_by_range(repos: Repositories) -> None:
    await repos.market.upsert_candles([candle(0, closed=False), candle(1), candle(2)])
    await repos.market.upsert_candles([candle(0, close=1.15, closed=True)])  # the forming candle closes
    rows = await repos.market.candles("EURUSDm", Timeframe.M1, at(minutes=0), at(minutes=1))
    assert [c.open_time for c in rows] == [at(minutes=0), at(minutes=1)]
    assert rows[0].close == 1.15 and rows[0].closed is True
    assert await repos.market.last_candle_time("EURUSDm", Timeframe.M1) == at(minutes=2)
    assert await repos.market.last_candle_time("EURUSDm", Timeframe.H1) is None


async def test_ticks_are_batched_and_spreads_summarised_by_hour(repos: Repositories) -> None:
    base = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
    ticks = [
        Tick(symbol="EURUSDm", bid=1.1, ask=1.1 + s, time=base + timedelta(seconds=i))
        for i, s in enumerate([0.0001, 0.0003])
    ]
    await repos.market.insert_ticks(ticks)
    await repos.market.insert_ticks([])  # nothing to do is not an error
    rows = await repos.market.spread_by_hour("EURUSDm", base - timedelta(hours=1), base + timedelta(hours=1))
    assert len(rows) == 1 and rows[0]["hour"] == 9 and rows[0]["ticks"] == 2
    assert rows[0]["max_spread"] == pytest.approx(0.0003)


async def test_the_news_calendar_is_unknown_until_synced_and_refreshes_only_the_future(repos: Repositories) -> None:
    assert await repos.news.upcoming(NOW) is None  # never synced: unknown, not "nothing soon"
    await repos.news.replace_upcoming(10, "CPI US", [at(days=-5), at(days=3), at(days=33)], at(days=-6))
    await repos.news.replace_upcoming(10, "CPI US", [at(days=4)], NOW)  # the refresh replaces the future rows
    upcoming = await repos.news.upcoming(NOW)
    assert upcoming == [UpcomingRelease(release_id=10, label="CPI US", scheduled_at=at(days=4))]
    only_past = await repos.news.upcoming(at(days=10))
    assert only_past == []  # synced, and nothing upcoming: an empty list is not None


# ------------------------------------------------------------------------------------------------------ strategy


async def test_intents_and_evaluations_are_recorded(repos: Repositories) -> None:
    intent = make_intent("AC1")
    await repos.strategy.record_intent(intent)
    await repos.strategy.record_intent(intent)
    assert await repos.strategy.get_intent(intent.intent_id) == intent
    assert await repos.strategy.recent_intents("AC1") == [intent]

    proposed = StrategyEvaluation(
        symbol="EURUSDm",
        event_at=at(minutes=-5),
        status="proposed",
        side=Side.BUY,
        entry_price=1.1,
        stop_loss=1.09,
        take_profit=1.12,
        cost_ratio=0.1,
        risk_reward_ratio=2.0,
        swept_level_kind="pdl",
        swept_level_price=1.095,
    )
    blocked = StrategyEvaluation(
        symbol="EURUSDm", event_at=at(minutes=-4), status="blocked", stage="no_sweep", detail="nothing swept"
    )
    await repos.strategy.record_evaluation(proposed)
    await repos.strategy.record_evaluation(proposed.model_copy(update={"entry_price": 1.101}))  # re-detection
    await repos.strategy.record_evaluation(blocked)
    rows = await repos.strategy.evaluations_since(at(hours=-1))
    assert [r.status for r in rows] == ["blocked", "proposed"]
    assert rows[1].entry_price == 1.101 and rows[1].side is Side.BUY


# ------------------------------------------------------------------------------------------------------ execution


async def test_a_command_is_persisted_once_and_idempotent_on_its_id(repos: Repositories) -> None:
    command = make_command("cmd-aaa")
    assert await repos.execution.insert(command, NOW) is True
    assert await repos.execution.insert(command, NOW) is False
    assert await repos.execution.get("cmd-aaa") == command
    assert await repos.execution.get("cmd-zzz") is None
    history = await repos.execution.transitions("cmd-aaa")
    assert [(h["from_state"], h["to_state"]) for h in history] == [(None, "PENDING")]


async def test_a_transition_is_a_compare_and_set_that_a_second_writer_cannot_repeat(repos: Repositories) -> None:
    pending = make_command("cmd-bbb")
    await repos.execution.insert(pending, NOW)
    sent = pending.model_copy(update={"state": CommandState.SENT, "sent_at": at(seconds=1)})
    await repos.execution.transition(pending, sent, "SENT", at(seconds=1))
    with pytest.raises(Conflict) as caught:  # a concurrent writer still believes it is PENDING
        await repos.execution.transition(pending, sent, "SENT", at(seconds=2))
    assert caught.value.code == "command_state_changed"

    done = sent.model_copy(
        update={
            "state": CommandState.EXECUTED,
            "filled_volume": 0.05,
            "average_price": 1.1002,
            "broker_position_id": "9001",
            "completed_at": at(seconds=3),
        }
    )
    await repos.execution.transition(sent, done, "REPORT_EXECUTED", at(seconds=3))
    stored = await repos.execution.get("cmd-bbb")
    assert stored == done
    assert [h["to_state"] for h in await repos.execution.transitions("cmd-bbb")] == ["PENDING", "SENT", "EXECUTED"]


async def test_in_doubt_commands_are_found_by_state(repos: Repositories) -> None:
    for command_id, state in [
        ("cmd-1", CommandState.PENDING),
        ("cmd-2", CommandState.SENT),
        ("cmd-3", CommandState.UNKNOWN),
        ("cmd-4", CommandState.FAILED),
        ("cmd-5", CommandState.RECONCILING),
    ]:
        await repos.execution.insert(make_command(command_id, state=state), NOW)
    in_doubt = await repos.execution.in_doubt()
    assert {c.command_id for c in in_doubt} == {"cmd-2", "cmd-3", "cmd-5"}
    assert {c.command_id for c in await repos.execution.in_doubt("OTHER")} == set()
    pending = await repos.execution.in_states([CommandState.PENDING])
    assert [c.command_id for c in pending] == ["cmd-1"]
    assert len(await repos.execution.recent(None, 3)) == 3


async def test_what_the_agent_reported_is_recorded(repos: Repositories) -> None:
    await repos.execution.insert(make_command("cmd-ccc"), NOW)
    await repos.execution.record_ack(
        AckRecord(command_id="cmd-ccc", agent_id="agent-1", status="ACCEPTED", received_at=NOW)
    )
    report = ReportRecord(
        report_id="rep-1",
        command_id="cmd-ccc",
        account_id="AC1",
        agent_id="agent-1",
        symbol="EURUSDm",
        side="BUY",
        status="FILLED",
        detail="ok",
        reported_at=NOW,
    )
    await repos.execution.record_report(report)
    await repos.execution.record_report(report)  # idempotent on the report id
    reconciled = ReconciliationRecord(
        command_id="cmd-ccc", account_id="AC1", outcome="not_found", attempts=1, detail="nothing yet", reconciled_at=NOW
    )
    await repos.execution.upsert_reconciliation(reconciled)
    await repos.execution.upsert_reconciliation(
        reconciled.model_copy(update={"outcome": "executed", "attempts": 2, "broker_position_id": "9001"})
    )
    rows = await repos.execution.reconciliations("AC1")
    assert len(rows) == 1 and rows[0].outcome == "executed" and rows[0].attempts == 2


# ------------------------------------------------------------------------------------------------------ events


async def test_the_event_store_keeps_each_event_once_and_filters(repos: Repositories) -> None:
    connected = AccountConnected(
        account_id="AC1", server="Exness-Real", currency="USD", environment=Environment.DEMO, correlation_id="corr-1"
    )
    lockout = LockoutEnabled(account_id="AC2", lockout_id="lk1", reason="Kill switch manuel", since=NOW)
    assert await repos.events.append(connected) is True
    assert await repos.events.append(connected) is False  # same id: not duplicated
    await repos.events.append(lockout)

    assert len(await repos.events.query()) == 2
    only_a = await repos.events.query(account_id="AC1")
    assert [r["type"] for r in only_a] == ["account.connected"] and only_a[0]["payload"]["server"] == "Exness-Real"
    assert [r["type"] for r in await repos.events.query(types=["risk.lockout_enabled"])] == ["risk.lockout_enabled"]
    assert len(await repos.events.query(correlation_id="corr-1")) == 1
    assert await repos.events.query(since=datetime.now(UTC) + timedelta(days=1)) == []
    counts = await repos.events.counts_by_type(datetime.now(UTC) - timedelta(days=1))
    assert counts == {"account.connected": 1, "risk.lockout_enabled": 1}


async def test_incidents_are_opened_and_resolved_once(repos: Repositories) -> None:
    incident = Incident(
        incident_id="inc-1",
        code="agent_heartbeat_stale",
        component="execution_agent",
        severity=Severity.HIGH,
        detail="no heartbeat for 40s",
        opened_at=NOW,
        account_id="AC1",
    )
    await repos.incidents.open(incident)
    await repos.incidents.open(incident)
    assert [i.incident_id for i in await repos.incidents.open_incidents()] == ["inc-1"]
    assert await repos.incidents.resolve("inc-1", at(minutes=5), "agent reconnected") is True
    assert await repos.incidents.resolve("inc-1", at(minutes=6), "again") is False
    assert await repos.incidents.open_incidents() == []
    recent = await repos.incidents.recent()
    assert recent[0].resolved_at == at(minutes=5) and recent[0].resolution == "agent reconnected"
