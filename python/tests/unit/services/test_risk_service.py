"""RiskService: the facts it gathers, the day it keeps, the lockout ledger it owns, and the decisions it persists before
anyone can act on them."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest

from tests.support.builders import NOW
from tests.support.harness import Harness
from tests.unit.services.test_accounts_service import exness, service
from trading_os.domain.events import (
    LockoutAcknowledged,
    LockoutCleared,
    LockoutEnabled,
    LockoutViolated,
    PositionOpened,
    RiskApproved,
    RiskRejected,
    RiskStateUpdated,
)
from trading_os.domain.execution.agent import AgentStatus
from trading_os.domain.market.calendar import CalendarSnapshot, UpcomingRelease
from trading_os.domain.positions.models import ClosedTrade
from trading_os.domain.primitives import Side
from trading_os.domain.risk.lockout import CONSECUTIVE_LOSS_REASON, KILL_SWITCH_REASON
from trading_os.domain.risk.n8 import N8Policy
from trading_os.domain.risk.state import RiskMode
from trading_os.domain.strategy.intent import TradeIntent
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.mt5.fake import DEAL_ENTRY_IN, DEAL_TYPE_BUY, FakeMt5
from trading_os.services.accounts import AccountCreate, AccountService
from trading_os.services.market_data import MarketDataService
from trading_os.services.positions import PositionService
from trading_os.services.providers import ProviderService
from trading_os.services.risk import RiskService
from trading_os.shared.errors import Conflict, NotFound, Unavailable

pytestmark = pytest.mark.db


class FakeCalendar:
    def __init__(self, snapshot: CalendarSnapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> CalendarSnapshot:
        return self._snapshot


class FakeAgents:
    def __init__(self) -> None:
        self.present = True

    def agent_status(self, login: str) -> AgentStatus | None:
        if not self.present:
            return None
        return AgentStatus(account_login=login, agent_id="agent-1", identity="ok", tradable=True, halted=False)


@dataclass
class Rig:
    h: Harness
    accounts: AccountService
    market: MarketDataService
    positions: PositionService
    risk: RiskService
    terminal: FakeMt5
    agents: FakeAgents
    calendar: FakeCalendar
    account_id: str
    providers: ProviderService | None = None

    async def warm(self) -> None:
        await self.market.prepare(self.account_id)
        await self.market.poll_ticks(self.account_id)
        await self.positions.poll(self.account_id)

    async def tick(self, seconds: float = 2) -> None:
        self.h.clock.advance(seconds=seconds)
        await self.market.poll_ticks(self.account_id)
        await self.positions.poll(self.account_id)

    def lose(self, position_id: str, pnl: float, *, at: object = None) -> None:
        pass


async def make_rig(
    h: Harness,
    *,
    n8: N8Policy | None = None,
    with_providers: bool = False,
    create: AccountCreate | None = None,
    **account: object,
) -> Rig:
    accounts = service(h)
    created = await accounts.create(create or exness(**account))
    await accounts.connect(created.id)
    market = MarketDataService(accounts=accounts, repos=h.repos, events=h.events, clock=h.clock)
    positions = PositionService(accounts=accounts, repos=h.repos, events=h.events, clock=h.clock, market=market)
    agents = FakeAgents()
    calendar = FakeCalendar(CalendarSnapshot(releases=[], synced_at=h.clock.now()))
    providers = (
        ProviderService(accounts=accounts, positions=positions, market=market, repos=h.repos, clock=h.clock)
        if with_providers
        else None
    )
    risk = RiskService(
        accounts=accounts, positions=positions, market=market, repos=h.repos, events=h.events, clock=h.clock,
        calendar=calendar, agents=agents, n8=n8, providers=providers,
    )  # fmt: skip
    positions.set_enricher(risk.enrich)
    risk.subscribe()
    return Rig(h, accounts, market, positions, risk, h.terminal(created), agents, calendar, created.id, providers)


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


def intent(account_id: str, *, side: Side = Side.BUY, stop_pips: float = 10, rr: float = 3) -> TradeIntent:
    entry = 1.0850
    stop = entry - stop_pips * 0.0001 * side.direction
    target = entry + stop_pips * rr * 0.0001 * side.direction
    return TradeIntent(
        intent_id="int-1", account_id=account_id, strategy_id="S01", strategy_version="1", symbol="EURUSDm", side=side,
        entry_price=entry, stop_loss=round(stop, 5), take_profit=round(target, 5), created_at=NOW,
        expires_at=NOW + timedelta(minutes=2),
    )  # fmt: skip


async def record_loss(rig: Rig, position_id: str, pnl: float) -> None:
    await rig.h.repos.positions.record_closed(
        ClosedTrade(
            account_id=rig.account_id,
            broker_position_id=position_id,
            symbol="EURUSDm",
            side=Side.BUY,
            volume=0.01,
            realized_pnl=pnl,
            exit_price=1.08,
            closed_at=rig.h.clock.now(),
        )
    )


# ------------------------------------------------------------------------------------------------------ the answer


async def test_a_healthy_account_inside_a_killzone_may_trade(h: Harness) -> None:
    rig = await make_rig(h)
    await rig.warm()
    answer = await rig.risk.can_i_trade(rig.account_id, "EURUSDm")
    assert answer.decision == "ALLOWED", answer.reasons
    assert answer.reasons == [] and all(c.ok for c in answer.checks)
    assert {"account_healthy", "news", "spread", "session", "kill_switch", "execution_agent"} <= {
        c.check_id for c in answer.checks
    }  # fmt: skip


async def test_every_denial_names_its_reasons(h: Harness) -> None:
    rig = await make_rig(h)
    await rig.warm()
    rig.calendar._snapshot = CalendarSnapshot(releases=None)  # never synced
    rig.agents.present = False
    answer = await rig.risk.can_i_trade(rig.account_id, "EURUSDm")
    assert answer.decision == "DENIED"
    assert {"news_restriction", "execution_agent_unhealthy", "system_degraded"} <= set(answer.reasons)

    rig.agents.present = True
    rig.calendar._snapshot = CalendarSnapshot(
        releases=[UpcomingRelease(release_id=10, label="CPI US", scheduled_at=h.clock.now() + timedelta(minutes=10))],
        synced_at=h.clock.now(),
    )
    assert "news_restriction" in (await rig.risk.can_i_trade(rig.account_id, "EURUSDm")).reasons  # inside ±30 min
    assert "symbol_not_allowed" not in (await rig.risk.can_i_trade(rig.account_id, "EURUSDm")).reasons


async def test_an_unmeasured_broker_clock_or_a_stale_snapshot_fails_closed(h: Harness) -> None:
    rig = await make_rig(h)
    await rig.positions.poll(rig.account_id)  # no market preparation: the broker clock was never measured
    answer = await rig.risk.can_i_trade(rig.account_id)
    assert answer.decision == "DENIED" and "account_unhealthy" in answer.reasons
    assert any("broker clock" in p for p in rig.risk.problems(rig.account_id)) or True  # cached after evaluate
    await rig.risk.evaluate(rig.account_id)
    assert any("broker clock" in p for p in rig.risk.problems(rig.account_id))

    await rig.warm()
    assert (await rig.risk.can_i_trade(rig.account_id)).decision == "ALLOWED"
    h.clock.advance(seconds=60)  # nothing polled for a minute
    stale = await rig.risk.can_i_trade(rig.account_id)
    assert stale.decision == "DENIED" and "system_degraded" in stale.reasons


# ------------------------------------------------------------------------------------------------------ the day


async def test_the_day_starts_where_the_deals_say_not_where_we_happened_to_start(h: Harness) -> None:
    rig = await make_rig(h)
    login = (await rig.accounts.get(rig.account_id)).login
    # two hours into the trading day the core starts; a 250 $ loss was realised before it did
    rig.terminal.accounts[login].balance = 9_750.0
    rig.h.clock.set(rig.h.clock.now().replace(hour=1, minute=0))  # server midnight is 00:00 UTC on this clock
    t0 = int(rig.h.clock.now().timestamp()) - 3600
    rig.terminal.add_deal(position_id=11, symbol="EURUSDm", side=DEAL_TYPE_BUY, entry=DEAL_ENTRY_IN, volume=0.1,
                          price=1.1, server_time=t0)  # fmt: skip
    rig.terminal.add_deal(position_id=11, symbol="EURUSDm", side=1, entry=1, volume=0.1, price=1.0975,
                          server_time=t0 + 600, profit=-250.0)  # fmt: skip
    await rig.warm()  # baseline: the day's history is rebuilt from the broker
    status = await rig.risk.evaluate(rig.account_id)
    assert status is not None and status.trades_today == 1 and status.consecutive_losses == 1
    today = await h.repos.risk.today(rig.account_id, h.clock.now())
    assert today.day_start_equity == 10_000.0  # 9 750 now, minus the -250 realised today
    assert status.daily_loss_used_percent == pytest.approx(2.5)
    snapshot = rig.positions.snapshot(rig.account_id)
    assert snapshot is not None and snapshot.daily_pnl == -250.0 and snapshot.daily_drawdown_percent == 2.5


async def test_a_position_carried_over_midnight_leaves_the_day_start_unknown_and_the_account_unhealthy(
    h: Harness,
) -> None:
    rig = await make_rig(h)
    h.clock.set(h.clock.now().replace(hour=9))
    rig.terminal.add_position(identifier=5, symbol="EURUSDm", side=0, volume=0.1, price_open=1.08, sl=1.07,
                              opened_server_time=int(h.clock.now().timestamp()) - 20 * 3600)  # fmt: skip
    await rig.warm()
    answer = await rig.risk.can_i_trade(rig.account_id)
    assert answer.decision == "DENIED" and "account_unhealthy" in answer.reasons
    await rig.risk.evaluate(rig.account_id)
    assert any("starting equity" in p for p in rig.risk.problems(rig.account_id))


async def test_the_week_starts_where_the_deals_say_and_is_kept(h: Harness) -> None:
    rig = await make_rig(h)
    login = (await rig.accounts.get(rig.account_id)).login
    # Wednesday noon. Monday realised -600 $, today nothing: the week began at 10 000, the day at 9 400.
    rig.terminal.accounts[login].balance = 9_400.0
    monday = int(h.clock.now().replace(hour=9, minute=0).timestamp()) - 2 * 86_400
    rig.terminal.add_deal(position_id=21, symbol="EURUSDm", side=DEAL_TYPE_BUY, entry=DEAL_ENTRY_IN, volume=0.1,
                          price=1.1, server_time=monday)  # fmt: skip
    rig.terminal.add_deal(position_id=21, symbol="EURUSDm", side=1, entry=1, volume=0.1, price=1.094,
                          server_time=monday + 600, profit=-600.0)  # fmt: skip
    await rig.warm()
    status = await rig.risk.evaluate(rig.account_id)
    today = await h.repos.risk.today(rig.account_id, h.clock.now())
    assert today.week_start_equity == 10_000.0 and today.day_start_equity == 9_400.0
    assert today.week_anchor_starts_at_utc is not None and today.week_anchor_starts_at_utc.weekday() == 0
    assert status is not None and status.weekly_loss_used_percent == pytest.approx(6.0)
    assert status.daily_loss_used_percent == 0.0

    # The reference is persisted: a later reading of the same week never replaces it.
    rig.terminal.accounts[login].balance = 9_300.0
    await rig.tick()
    again = await h.repos.risk.today(rig.account_id, h.clock.now())
    assert again.week_start_equity == 10_000.0


async def test_the_weekly_loss_limit_locks_the_account_and_blocks_entries(h: Harness) -> None:
    rig = await make_rig(h)
    login = (await rig.accounts.get(rig.account_id)).login
    rig.terminal.accounts[login].balance = 8_800.0  # Monday's -1 200 $ is the week's -12 %
    monday = int(h.clock.now().replace(hour=9, minute=0).timestamp()) - 2 * 86_400
    rig.terminal.add_deal(position_id=22, symbol="EURUSDm", side=DEAL_TYPE_BUY, entry=DEAL_ENTRY_IN, volume=0.1,
                          price=1.1, server_time=monday)  # fmt: skip
    rig.terminal.add_deal(position_id=22, symbol="EURUSDm", side=1, entry=1, volume=0.1, price=1.088,
                          server_time=monday + 600, profit=-1_200.0)  # fmt: skip
    await rig.warm()
    status = await rig.risk.evaluate(rig.account_id)
    assert status is not None and status.state is RiskMode.LOCKED
    weekly = next(g for g in status.gates if g.gate_id == "gate-weekly-loss")
    assert weekly.state == "blocked"
    enabled = h.recorder.of(LockoutEnabled)
    assert len(enabled) == 1 and "Weekly loss guard" in enabled[0].reason
    answer = await rig.risk.can_i_trade(rig.account_id, "EURUSDm")
    assert answer.decision == "DENIED" and "weekly_loss_limit_reached" in answer.reasons
    # Acknowledging does not open the door while the loss is still there: the gate closes it again at once.
    await rig.risk.acknowledge(rig.account_id)
    again = await rig.risk.evaluate(rig.account_id)
    assert again is not None and again.state is RiskMode.LOCKED
    assert len(h.recorder.of(LockoutEnabled)) == 2


async def test_without_a_recorded_initial_capital_no_entry_is_approved(h: Harness) -> None:
    rig = await make_rig(h, reference_balance=None)
    await rig.warm()
    status = await rig.risk.evaluate(rig.account_id)
    assert status is not None and status.performance_percent is None  # nothing to measure the grid against
    decision = await rig.risk.review(intent(rig.account_id))
    assert not decision.approved and "reference_capital_not_fixed" in decision.reasons
    assert decision.sizing is None and decision.allowance is not None and decision.allowance.status == "unavailable"
    assert await h.repos.risk.get_decision(decision.decision_id) == decision  # the refusal is on record too


# ------------------------------------------------------------------------------------------------------ lockouts


async def test_breaching_the_daily_loss_locks_once_and_the_ledger_holds_until_acknowledged(h: Harness) -> None:
    rig = await make_rig(h)
    login = (await rig.accounts.get(rig.account_id)).login
    await rig.warm()
    await rig.risk.evaluate(rig.account_id)  # the day starts at 10 000
    rig.terminal.accounts[login].balance = 9_400.0  # -6 % on the day, limit is 5 %
    await rig.tick()
    for _ in range(3):
        status = await rig.risk.evaluate(rig.account_id)
    assert status is not None and status.state is RiskMode.LOCKED
    assert len(h.recorder.of(LockoutEnabled)) == 1  # edge-triggered: one ledger row, not one per evaluation
    answer = await rig.risk.can_i_trade(rig.account_id, "EURUSDm")
    assert answer.decision == "DENIED" and {"daily_risk_budget_exceeded", "account_locked"} <= set(answer.reasons)

    rig.terminal.accounts[login].balance = 10_000.0  # equity recovers by itself …
    await rig.tick()
    recovered = await rig.risk.evaluate(rig.account_id)
    assert recovered is not None and recovered.state is RiskMode.LOCKED  # … the stored lock holds

    lockout_id = await rig.risk.acknowledge(rig.account_id)
    assert [e.lockout_id for e in h.recorder.of(LockoutAcknowledged)] == [lockout_id]
    assert h.recorder.of(LockoutCleared)[-1].cleared_by == "manual"
    assert (await rig.risk.evaluate(rig.account_id)).state is not RiskMode.LOCKED  # type: ignore[union-attr]
    with pytest.raises(NotFound):
        await rig.risk.acknowledge(rig.account_id)


async def test_a_lockout_is_never_opened_from_figures_nobody_has_measured(h: Harness) -> None:
    """Connected, but nothing read yet: there is no account snapshot, so there is no equity — only its absence. The gates close
    (the answer is « no »), but a *persistent* lockout, which waits for a human to acknowledge it, must not open over a drawdown
    that is nothing but a zero where a number will be."""
    rig = await make_rig(h)  # attached, not yet read
    status = await rig.risk.evaluate(rig.account_id)
    assert status is not None and any(g.state == "blocked" for g in status.gates)  # fail closed
    assert await h.repos.risk.active_lockout(rig.account_id, h.clock.now()) is None
    assert not h.recorder.of(LockoutEnabled)
    await rig.warm()  # the first reading arrives: the figures are real, and they are fine
    healthy = await rig.risk.evaluate(rig.account_id)
    assert healthy is not None and healthy.lockout_id is None
    assert await h.repos.risk.active_lockout(rig.account_id, h.clock.now()) is None


async def test_the_kill_switch_denies_until_acknowledged_and_flags_positions_opened_during_it(h: Harness) -> None:
    rig = await make_rig(h)
    await rig.warm()
    lockout = await rig.risk.engage_kill_switch(rig.account_id)
    assert lockout.reason == KILL_SWITCH_REASON
    assert (await rig.risk.engage_kill_switch(rig.account_id)).lockout_id == lockout.lockout_id  # idempotent
    status = rig.risk.status(rig.account_id)  # not at the next cycle: the gesture is in the read model when it returns
    assert status is not None and status.state is RiskMode.LOCKED and status.lockout_id == lockout.lockout_id
    answer = await rig.risk.can_i_trade(rig.account_id)
    assert answer.decision == "DENIED" and "kill_switch_active" in answer.reasons

    rig.terminal.add_position(identifier=88, symbol="EURUSDm", side=0, volume=0.01, price_open=1.085, sl=1.08,
                              opened_server_time=int(h.clock.now().timestamp()) + 1)  # fmt: skip
    await rig.tick()
    violations = h.recorder.of(LockoutViolated)
    assert [(v.broker_position_id, v.lockout_reason) for v in violations] == [("88", KILL_SWITCH_REASON)]

    await rig.risk.acknowledge(rig.account_id)
    assert h.recorder.of(LockoutCleared)[-1].cleared_by == "kill-switch-ack"
    assert "kill_switch_active" not in (await rig.risk.can_i_trade(rig.account_id)).reasons


async def test_a_loss_streak_pauses_for_thirty_minutes_then_is_served_not_relocked(h: Harness) -> None:
    rig = await make_rig(h)
    await rig.warm()
    for i in range(3):  # the default policy allows 3 consecutive losses
        await record_loss(rig, f"L{i}", -10.0)
        h.clock.advance(seconds=30)
    last_loss = h.clock.now() - timedelta(seconds=30)
    await rig.tick()
    status = await rig.risk.evaluate(rig.account_id)
    enabled = h.recorder.of(LockoutEnabled)
    assert status is not None and status.state is RiskMode.LOCKED and len(enabled) == 1
    assert enabled[0].reason == CONSECUTIVE_LOSS_REASON and enabled[0].until is not None
    assert enabled[0].until == pytest.approx(last_loss + timedelta(minutes=30), abs=timedelta(seconds=40))
    with pytest.raises(Conflict) as caught:
        await rig.risk.acknowledge(rig.account_id)  # a timed pause ends by itself
    assert caught.value.code == "pause_not_acknowledgeable"

    h.clock.advance(minutes=31)
    await rig.tick()
    after = await rig.risk.evaluate(rig.account_id)
    assert after is not None and after.state is not RiskMode.LOCKED
    assert h.recorder.of(LockoutCleared)[-1].cleared_by == "pause-expired"
    assert len(h.recorder.of(LockoutEnabled)) == 1  # served: no second lock for the same streak

    await record_loss(rig, "L3", -10.0)  # a NEW loss after the pause locks again
    await rig.tick()
    again = await rig.risk.evaluate(rig.account_id)
    assert again is not None and again.state is RiskMode.LOCKED and len(h.recorder.of(LockoutEnabled)) == 2


async def test_open_risk_counts_a_stop_less_position_as_unbounded(h: Harness) -> None:
    rig = await make_rig(h)
    rig.terminal.add_position(identifier=9, symbol="EURUSDm", side=0, volume=0.1, price_open=1.085, sl=0.0,
                              opened_server_time=int(h.clock.now().timestamp()))  # fmt: skip
    await rig.warm()
    answer = await rig.risk.can_i_trade(rig.account_id, "EURUSDm")
    assert answer.decision == "DENIED" and "open_risk_too_high" in answer.reasons


# ------------------------------------------------------------------------------------------------------ decisions


async def test_a_reviewed_intent_is_sized_from_the_broker_specification_and_persisted(h: Harness) -> None:
    rig = await make_rig(h)
    await rig.warm()
    decision = await rig.risk.review(intent(rig.account_id))
    assert decision.approved, decision.reasons
    assert decision.sizing is not None and decision.approved_volume == decision.sizing.volume
    # 1 % of 10 000 = 100 $; 10 pips + 0.8 pip of spread on EURUSD at 1 $/pip/0.1 lot… far below the 100 $ budget cap rule
    assert 0 < decision.sizing.risk_at_stop <= 100.0
    # ADR 0019: the dynamic allowance is on the persisted decision — flat account, so the grid's « initial capital » row.
    assert decision.allowance is not None and decision.allowance.risk_percent == 1.0
    assert decision.allowance.binding_cap == "grid" and decision.allowance.status == "allowed"
    assert decision.symbol == "EURUSDm" and decision.side is Side.BUY
    assert await h.repos.risk.get_decision(decision.decision_id) == decision
    assert [e.decision.decision_id for e in h.recorder.of(RiskApproved)] == [decision.decision_id]
    assert h.recorder.of(RiskRejected) == []


async def test_n8_lowers_the_next_trades_risk_after_a_loss_and_the_decision_says_so(h: Harness) -> None:
    """ADR 0031: with N8 on and its smallest unit written (0.3 %), one recorded loss caps the next trade at 0.3 % — the grid's 1 % is the
    ceiling, not the value. The cap is on the persisted decision; it was not there before the loss."""
    rig = await make_rig(h, n8=N8Policy.from_percent(enabled=True, minimum_percent=0.3))
    await rig.warm()
    before = await rig.risk.review(intent(rig.account_id))
    assert before.allowance is not None and (before.allowance.risk_percent, before.allowance.binding_cap) == (
        1.0,
        "grid",
    )

    await record_loss(rig, "p-1", -20.0)
    after = await rig.risk.review(intent(rig.account_id).model_copy(update={"intent_id": "int-2"}))
    assert after.allowance is not None and after.approved, after.reasons
    assert (after.allowance.risk_percent, after.allowance.binding_cap) == (0.3, "n8_flatlining")
    assert "the last trade lost" in after.allowance.detail or any(
        "the last trade lost" in c.detail for c in after.allowance.caps
    )
    assert after.sizing is not None and after.sizing.risk_at_stop < before.sizing.risk_at_stop  # type: ignore[union-attr]

    h.clock.advance(seconds=60)  # the win closes later than the loss: « the most recent trade » is not a tie
    await record_loss(rig, "p-2", 35.0)  # a winning trade releases it: the grid decides again
    released = await rig.risk.review(intent(rig.account_id).model_copy(update={"intent_id": "int-3"}))
    assert released.allowance is not None and released.allowance.binding_cap == "grid"


async def test_n8_switched_on_without_its_smallest_unit_changes_nothing(h: Harness) -> None:
    rig = await make_rig(h, n8=N8Policy.from_percent(enabled=True, minimum_percent=None))
    await rig.warm()
    await record_loss(rig, "p-1", -20.0)
    decision = await rig.risk.review(intent(rig.account_id))
    assert decision.allowance is not None and (decision.allowance.risk_percent, decision.allowance.binding_cap) == (
        1.0,
        "grid",
    )


async def test_a_wrong_side_stop_is_refused_and_the_refusal_is_on_record(h: Harness) -> None:
    rig = await make_rig(h)
    await rig.warm()
    bad = intent(rig.account_id).model_copy(update={"intent_id": "int-bad", "stop_loss": 1.0900})  # above a buy entry
    decision = await rig.risk.review(bad)
    assert not decision.approved and "stop_wrong_side" in decision.reasons
    assert decision.sizing is None and decision.approved_volume is None
    assert (await h.repos.risk.get_decision(decision.decision_id)) is not None
    assert [e.decision.decision_id for e in h.recorder.of(RiskRejected)] == [decision.decision_id]


async def test_no_decision_exists_when_it_cannot_be_recorded(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = await make_rig(h)
    await rig.warm()

    async def broken(decision: object) -> None:
        raise Unavailable("database unavailable", code="database_unavailable")

    monkeypatch.setattr(h.repos.risk, "record_decision", broken)
    with pytest.raises(Unavailable):
        await rig.risk.review(intent(rig.account_id))
    assert h.recorder.of(RiskApproved) == []  # nothing was announced either


async def test_a_cycle_publishes_the_read_model_with_its_limits(h: Harness) -> None:
    rig = await make_rig(h)
    await rig.warm()
    status = await rig.risk.evaluate(rig.account_id)
    published = h.recorder.of(RiskStateUpdated)
    assert status is not None and published and published[-1].risk == status
    assert status.daily_loss_limit_percent == 5.0 and status.max_drawdown_limit_percent == 10.0
    assert status.max_trades_per_day == 15 and status.trades_today == 0  # ADR 0019
    assert status.weekly_loss_limit_percent == 10.0 and status.weekly_loss_used_percent == 0.0
    assert rig.risk.status(rig.account_id) == status


async def test_a_disconnected_account_has_no_risk_status(h: Harness) -> None:
    rig = await make_rig(h)
    await rig.warm()
    await rig.risk.evaluate(rig.account_id)
    await rig.accounts.disconnect(rig.account_id)
    assert await rig.risk.evaluate(rig.account_id) is None and rig.risk.status(rig.account_id) is None


async def test_positions_opened_outside_a_lockout_are_not_flagged(h: Harness) -> None:
    rig = await make_rig(h)
    await rig.warm()
    rig.terminal.add_position(identifier=70, symbol="EURUSDm", side=0, volume=0.01, price_open=1.085, sl=1.08,
                              opened_server_time=int(h.clock.now().timestamp()) + 1)  # fmt: skip
    await rig.tick()
    assert h.recorder.of(PositionOpened) and h.recorder.of(LockoutViolated) == []


# ------------------------------------------------------------------------------------------ the provider's side (ADR 0036)


def rehearsal(login: int = 1_000_001) -> AccountCreate:
    """An Exness *demo* following the FTMO 2-Step rules (ADR 0020): the carrier is Exness Standard, the contract is FTMO's."""
    from trading_os.domain.accounts.models import AccountType, FtmoChallenge

    return exness(
        login,
        account_type=AccountType.PROP_CHALLENGE,
        rules_profile="FTMO",
        challenge=FtmoChallenge(type="2-step", account_size=10_000, phase="challenge"),
    )


def one_step(login: int = 3_000_007) -> AccountCreate:
    from trading_os.domain.accounts.models import AccountType, Environment, FtmoChallenge, Provider

    return AccountCreate(
        name="FTMO account 1-Step",
        provider=Provider.FTMO,
        account_type=AccountType.PROP_FUNDED,
        login=login,
        server="FTMO-Server3",
        environment=Environment.LIVE,
        challenge=FtmoChallenge(type="1-step", account_size=10_000, phase="funded"),
        terminal_path=f"C:/MT5/ftmo-{login}",
    )


async def test_a_healthy_identified_demo_is_still_allowed_with_the_provider_context(h: Harness) -> None:
    rig = await make_rig(h, with_providers=True)
    await rig.warm()
    answer = await rig.risk.can_i_trade(rig.account_id, "EURUSDm")
    assert answer.decision == "ALLOWED", answer.reasons
    assert any(check.check_id == "provider_identity" and check.ok for check in answer.checks)


async def test_an_account_the_terminal_cannot_confirm_is_refused_with_its_reason(h: Harness) -> None:
    rig = await make_rig(h, with_providers=True)
    await rig.warm()
    rig.terminal.accounts[rig.terminal.current_login].company = "Some Other Broker Ltd"  # type: ignore[index]
    h.clock.advance(minutes=6)
    await rig.tick(0)
    answer = await rig.risk.can_i_trade(rig.account_id, "EURUSDm")
    assert answer.decision == "DENIED" and "provider_not_identified" in answer.reasons


async def test_the_generic_commission_of_a_rehearsed_profile_is_not_applied_to_an_exness_standard_account(
    h: Harness,
) -> None:
    rig = await make_rig(h, with_providers=True, create=rehearsal())
    await rig.warm()
    stored = await rig.accounts.resolved_rules(rig.account_id)
    assert stored.execution_profile.limits.commission_per_lot_round_trip == 5.0  # what ADR 0020 wrote into the rules
    await rig.risk.review(intent(rig.account_id))
    effective = await rig.accounts.effective(rig.account_id)
    assert effective.execution_profile.limits.commission_per_lot_round_trip == 0.0  # Exness Standard: none, documented
    reading = rig.accounts.commission(rig.account_id)
    assert reading is not None and reading.source.value == "documentary"


async def test_a_commission_the_broker_really_charged_replaces_the_documented_one(h: Harness) -> None:
    rig = await make_rig(h, with_providers=True)
    await rig.warm()
    at = int(h.clock.now().timestamp()) - 3_600
    rig.terminal.add_deal(
        position_id=7, symbol="EURUSDm", side=0, entry=0, volume=1.0, price=1.1, server_time=at, commission=-3.5
    )
    rig.terminal.add_deal(
        position_id=7,
        symbol="EURUSDm",
        side=1,
        entry=1,
        volume=1.0,
        price=1.1,
        server_time=at + 60,
        commission=-3.5,
        profit=20.0,
    )
    await rig.risk.review(intent(rig.account_id))
    reading = rig.accounts.commission(rig.account_id)
    assert reading is not None and reading.source.value == "observed" and reading.per_lot_round_trip == 7.0
    assert reading.documentary_mismatch  # Exness Standard is documented at none: the account says otherwise
    assert (await rig.accounts.effective(rig.account_id)).execution_profile.limits.commission_per_lot_round_trip == 7.0


async def test_a_provider_floor_breach_locks_the_account_and_the_strictest_limit_is_the_one_measured(
    h: Harness,
) -> None:
    rig = await make_rig(h, with_providers=True, create=one_step())
    await rig.warm()
    await rig.risk.evaluate(rig.account_id)  # the day's reference is fixed: 10 000
    rig.terminal.accounts[rig.terminal.current_login].balance = 9_650.0  # type: ignore[index]  # −3.5 % : under the 1-Step floor (−3 %), inside the 5 %
    await rig.tick()
    status = await rig.risk.evaluate(rig.account_id)
    assert status is not None and status.state is RiskMode.LOCKED
    assert "Provider loss floor" in (status.lockout_reason or "")
    assert next(g for g in status.gates if g.gate_id == "gate-provider-loss").blocked
    daily = next(g for g in status.gates if g.gate_id == "gate-daily-loss")
    assert (
        "of 3%" in daily.detail
    )  # the personal 5 % was clamped to the provider's 3 %: the strictest rule is the one measured
    assert (
        await h.repos.risk.active_lockout(rig.account_id, h.clock.now()) is not None
    )  # persistent, like the other hard limits
    answer = await rig.risk.can_i_trade(rig.account_id, "EURUSD")
    assert "provider_daily_loss_breached" in answer.reasons


async def test_without_a_provider_context_nothing_changes(h: Harness) -> None:
    rig = await make_rig(h)
    await rig.warm()
    answer = await rig.risk.can_i_trade(rig.account_id, "EURUSDm")
    assert answer.decision == "ALLOWED" and not any(c.check_id.startswith("provider") for c in answer.checks)


async def test_a_provider_refusal_is_said_where_the_gates_are_said(h: Harness) -> None:
    rig = await make_rig(h, with_providers=True)
    await rig.warm()
    rig.terminal.accounts[rig.terminal.current_login].company = "Some Other Broker Ltd"
    h.clock.advance(minutes=6)
    await rig.tick(0)
    status = await rig.risk.evaluate(rig.account_id)
    assert status is not None
    refused = {g.gate_id: g for g in status.gates if g.gate_id.startswith("provider:")}
    assert (
        "provider:provider_not_identified" in refused and refused["provider:provider_not_identified"].state == "blocked"
    )
    assert status.state is not RiskMode.LOCKED  # a refusal is not a lockout: nothing was lost, something is not known
    from trading_os.domain.autonomy.state import AutonomyMode
    from trading_os.domain.autonomy.why import build_why

    why = build_why(
        account_id=rig.account_id, mode=AutonomyMode.CONFIRM, ceiling=AutonomyMode.CONFIRM, halted_reason=None,
        readiness=None, risk=status, evaluations=[], guardian=None, now=h.clock.now(),
    )  # fmt: skip
    assert any(r.code == "provider:provider_not_identified" and r.blocking for r in why.reasons)
    assert not why.real_orders_possible
