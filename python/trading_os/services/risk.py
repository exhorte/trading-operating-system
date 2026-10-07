"""The Risk Engine as a service: **the single control point before execution** (ADR 0007).

Strategy → TradeIntent → ``review`` → RiskDecision → ExecutionService. Nothing else turns an intent into an order, and an
order without an approved, unexpired, matching decision is refused by the execution engine.

What this service adds to the pure domain (``domain/risk``):

* gathers the facts — account figures, positions, specifications, the day's trades and loss streak, the lockout ledger, the
  news calendar, the plumbing's health — and builds the ``TradingContext`` the domain evaluates;
* keeps the **trading-day anchor** (server midnight, via the measured broker clock) and the day's starting equity, which it
  derives from the deal history when the core starts mid-day instead of trusting the first equity it happens to see;
* owns the **lockout ledger**: edge-triggered opening, expiry of timed pauses, the kill switch, acknowledgement;
* persists every decision *before* returning it, so an approval that is not on record cannot exist.

Everything unknown fails closed: an unmeasured clock, a missing starting equity, an unreadable database all make the account
« unhealthy » and the answer DENIED, with the reason in the response.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from trading_os.domain.accounts.models import Account, AccountSnapshot
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
from trading_os.domain.market.calendar import CalendarSnapshot
from trading_os.domain.market.sessions import in_trading_window, window_name_at
from trading_os.domain.positions.models import Position
from trading_os.domain.risk.decision import (
    CanITradeResult,
    HealthFlags,
    IntentReview,
    RiskDecision,
    TradingContext,
    can_i_trade,
    decide,
)
from trading_os.domain.risk.evaluate import RiskInputs, evaluate_risk_state
from trading_os.domain.risk.exposure import currency_exposure, max_correlated_exposure, open_risk
from trading_os.domain.risk.lockout import (
    CONSECUTIVE_LOSS_GATE_ID,
    CONSECUTIVE_LOSS_REASON,
    KILL_SWITCH_REASON,
    ActiveLockout,
    apply_active_lockout,
    cleared_by_for_ack,
    detect_consecutive_loss_pause,
    detect_new_lockout,
)
from trading_os.domain.risk.state import RiskState
from trading_os.domain.risk.trading_day import RiskToday, resolve_today_start_utc
from trading_os.domain.risk.view import RiskStatus, to_risk_status
from trading_os.domain.strategy.intent import TradeIntent
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.services.accounts import AccountService
from trading_os.services.market_data import MarketDataService
from trading_os.services.positions import PositionService
from trading_os.shared.errors import Conflict, NotFound, Unavailable
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.ids import new_id
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

SNAPSHOT_FRESH_FOR = timedelta(seconds=15)
DAY_JUST_STARTED = timedelta(minutes=2)  # within this, the equity seen now *is* the day's starting equity


class CalendarSource(Protocol):
    def snapshot(self) -> CalendarSnapshot: ...


class AgentDirectory(Protocol):
    def agent_status(self, login: str) -> AgentStatus | None: ...


@dataclass
class _Cache:
    status: RiskStatus | None = None
    day_start_equity: float | None = None
    unhealthy: list[str] = field(default_factory=list)


@dataclass
class _Built:
    context: TradingContext
    today: RiskToday
    problems: list[str]


class RiskService:
    def __init__(
        self,
        *,
        accounts: AccountService,
        positions: PositionService,
        market: MarketDataService,
        repos: Repositories,
        events: EventDispatcher,
        clock: Clock,
        calendar: CalendarSource,
        agents: AgentDirectory,
        autonomy_permits_entries: Callable[[], bool] = lambda: True,
        halted: Callable[[], bool] = lambda: False,
    ) -> None:
        self._accounts = accounts
        self._positions = positions
        self._market = market
        self._repos = repos
        self._events = events
        self._clock = clock
        self._calendar = calendar
        self._agents = agents
        self._autonomy_permits = autonomy_permits_entries
        self._halted = halted
        self._cache: dict[str, _Cache] = {}
        self.last_error: str | None = None
        self.last_cycle_at: datetime | None = None

    def wire(self, *, autonomy_permits_entries: Callable[[], bool], halted: Callable[[], bool]) -> None:
        self._autonomy_permits = autonomy_permits_entries
        self._halted = halted

    def subscribe(self) -> None:
        """Positions opened during a lockout are flagged the instant they are seen (T02c)."""
        self._events.subscribe(PositionOpened, self._on_position_opened)

    # ------------------------------------------------------------------------------------------ reading
    def status(self, account_id: str) -> RiskStatus | None:
        cache = self._cache.get(account_id)
        return cache.status if cache else None

    def problems(self, account_id: str) -> list[str]:
        cache = self._cache.get(account_id)
        return list(cache.unhealthy) if cache else []

    def forget(self, account_id: str) -> None:
        self._cache.pop(account_id, None)

    # ------------------------------------------------------------------------------------------ the context
    async def _build(self, account_id: str, *, symbol: str | None = None) -> _Built:
        now = self._clock.now()
        account = await self._accounts.effective(account_id)
        session = self._accounts.session(account_id)
        snapshot = self._positions.snapshot(account_id)
        positions = self._positions.positions(account_id)
        problems: list[str] = []

        if session is None or snapshot is None:
            problems.append("account not connected" if session is None else "no account snapshot yet")
        elif now - snapshot.observed_at > SNAPSHOT_FRESH_FOR:
            problems.append(f"account snapshot is {int((now - snapshot.observed_at).total_seconds())}s old")
        if snapshot is not None and snapshot.trade_allowed is False:
            problems.append("trading is not allowed on this account in the terminal")

        today = RiskToday()
        database_ok = True
        try:
            today = await self._today(
                account, session.client.offset_known if session else False, snapshot, positions, now
            )
        except Unavailable:
            database_ok = False
            problems.append("database unavailable: today's trades and loss streak are unknown")
        day_start = today.day_start_equity
        if database_ok and session is not None and snapshot is not None:
            if not session.client.offset_known:
                problems.append("the broker clock is not measured yet: the trading day is unknown")
            elif day_start is None:
                problems.append("the day's starting equity is unknown")

        balance = snapshot.balance if snapshot else 0.0
        equity = snapshot.equity if snapshot else 0.0
        profile = account.risk_profile
        reference = profile.drawdown.reference_balance or balance

        specs = self._market.specs(account_id)
        report = open_risk(positions, specs, balance)
        exposure = currency_exposure(positions, specs, report.per_position, balance)
        correlated, key = max_correlated_exposure(exposure)

        tick = self._market.tick(account_id, symbol) if symbol else None
        cap = account.execution_profile.limits.max_spread_by_symbol.get(symbol or "")
        calendar = self._calendar.snapshot().usable(now, timedelta(hours=profile.news.calendar_max_age_hours))
        feed_ok, feed_detail = self._market.feed_status(account_id, now)
        if not feed_ok:
            problems.append(f"market data: {feed_detail}")
        status = self._agents.agent_status(str(account.login))
        if status is None:
            agent_problem = "no execution agent connected for this account"
        elif not status.healthy_for_orders:
            agent_problem = f"execution agent not ready (identity {status.identity}, tradable {status.tradable})"
        else:
            agent_problem = None

        inputs = RiskInputs(
            account_id=account_id,
            now=now,
            profile=profile,
            initial_balance=reference,
            day_start_equity=day_start if day_start is not None else equity,
            equity=equity,
            balance=balance,
            open_risk_percent=report.percent,
            unprotected_positions=tuple(report.unprotected),
            unmeasured_positions=tuple(report.unknown_spec),
            correlated_exposure_percent=correlated,
            correlated_key=key,
            open_positions=len(positions),
            trades_today=today.trades_today if database_ok else None,
            consecutive_losses=await self._streak_for_gate(account_id, today) if database_ok else None,
            spread=tick.spread if tick else None,
            spread_cap=cap,
            agent_connected=status is not None,
            in_trading_window=in_trading_window(now, account.trading_rules.trading_windows),
            window_label=window_name_at(now, account.trading_rules.trading_windows),
            calendar=tuple(calendar) if calendar is not None else None,
        )
        health = HealthFlags(
            account_healthy=not problems,
            broker_connected=self._positions.terminal_connected(account_id),
            mt5_healthy=self._positions.failures(account_id)[0] == 0 and feed_ok and session is not None,
            execution_agent_healthy=agent_problem is None,
            account_trading_enabled=account.trading_enabled,
            kill_switch_active=self._halted(),
            autonomy_permits_entries=self._autonomy_permits(),
        )
        context = TradingContext(
            risk=inputs,
            health=health,
            allowed_symbols=frozenset(account.trading_rules.allowed_symbols)
            if account.trading_rules.allowed_symbols
            else None,
            active_lockout=today.active_lockout,
            positions=tuple(positions),
            specs=specs,
        )
        if agent_problem:
            problems.append(agent_problem)
        return _Built(context, today, problems)

    async def _streak_for_gate(self, account_id: str, today: RiskToday) -> int:
        """The loss streak the gate sees. A streak whose last loss is no later than the end of a pause already served
        has been paid for: it must not lock the account a second time (only a *new* loss does)."""
        if today.consecutive_losses == 0 or today.last_loss_at is None:
            return today.consecutive_losses
        served_until = await self._repos.risk.last_pause_end(account_id)
        if served_until is not None and today.last_loss_at <= served_until <= self._clock.now():
            return 0
        return today.consecutive_losses

    async def _today(
        self,
        account: Account,
        offset_known: bool,
        snapshot: AccountSnapshot | None,
        positions: list[Position],
        now: datetime,
    ) -> RiskToday:
        today = await self._repos.risk.today(account.id, now)
        session = self._accounts.session(account.id)
        if session is None or snapshot is None or not offset_known:
            return today
        start = resolve_today_start_utc(now, session.client.offset)
        if today.day_anchor_starts_at_utc != start:
            await self._repos.risk.record_anchor(account.id, start)
            today = await self._repos.risk.today(account.id, now)
        if today.day_start_equity is None:
            estimate = await self._estimate_day_start(account.id, start, snapshot, positions, now)
            if estimate is not None and await self._repos.risk.confirm_day_start_equity(account.id, start, estimate):
                today = today.model_copy(update={"day_start_equity": estimate})
        cache = self._cache.setdefault(account.id, _Cache())
        cache.day_start_equity = today.day_start_equity
        return today

    async def _estimate_day_start(
        self, account_id: str, start: datetime, snapshot: AccountSnapshot, positions: list[Position], now: datetime
    ) -> float | None:
        """The equity the day started with. Right after the day began, the equity seen now is it. Later (the core was off,
        or started mid-day) it is the balance less what the day has realised — valid only if nothing was carried across
        midnight, whose floating result at that moment cannot be reconstructed: then it stays unknown, never guessed."""
        if not self._positions.baselined(account_id):
            return None  # the day's trades are still being rebuilt from the broker: not yet
        if now - start <= DAY_JUST_STARTED:
            return snapshot.equity
        if any((p.opened_at or now) < start for p in positions):
            return None
        realised = sum(t.realized_pnl for t in await self._repos.positions.closed_between(account_id, start, now))
        return round(snapshot.balance - realised, 2)

    # ------------------------------------------------------------------------------------------ the cycle
    async def evaluate(self, account_id: str) -> RiskStatus | None:
        """One risk cycle for one account: evaluate, run the lockout ledger, publish the read model."""
        if not self._accounts.is_connected(account_id):
            self.forget(account_id)
            return None
        try:
            built = await self._build(account_id)
            state = await self._run_lockouts(account_id, built)
        except Unavailable as error:
            self.last_error = error.safe_message
            return self.status(account_id)
        status = to_risk_status(state, built.context.risk.profile)
        cache = self._cache.setdefault(account_id, _Cache())
        cache.status, cache.unhealthy = status, built.problems
        self.last_cycle_at, self.last_error = self._clock.now(), None
        await self._events.publish(RiskStateUpdated(account_id=account_id, risk=status))
        return status

    async def _run_lockouts(self, account_id: str, built: _Built) -> RiskState:
        ctx, now = built.context, built.context.risk.now
        profile = ctx.risk.profile
        state = evaluate_risk_state(ctx.risk)
        for lockout_id in await self._repos.risk.expire_pauses(account_id, now):
            await self._events.publish(
                LockoutCleared(account_id=account_id, lockout_id=lockout_id, cleared_by="pause-expired")
            )
        active = ctx.active_lockout
        if active is None:
            hard_blocked = [g for g in state.gates if g.blocked and g.gate_id in _HARD_GATES]
            only_streak = bool(hard_blocked) and all(g.gate_id == CONSECUTIVE_LOSS_GATE_ID for g in hard_blocked)
            new = (
                detect_consecutive_loss_pause(
                    state, None, built.today.last_loss_at, profile.consecutive_loss_pause_minutes
                )
                if only_streak
                else detect_new_lockout(state, None)
            )
            if new is not None:
                active = await self._open_lockout(account_id, new.reason, new.until, now)
        return apply_active_lockout(state, active, now)

    async def _open_lockout(self, account_id: str, reason: str, until: datetime | None, now: datetime) -> ActiveLockout:
        lockout_id = new_id("lockout")
        await self._repos.risk.open_lockout(lockout_id, account_id, reason, now, until)  # persisted first
        await self._events.publish(
            LockoutEnabled(account_id=account_id, lockout_id=lockout_id, reason=reason, since=now, until=until)
        )
        return ActiveLockout(lockout_id=lockout_id, reason=reason, since=now, until=until)

    # ------------------------------------------------------------------------------------------ kill switch / ack
    async def engage_kill_switch(self, account_id: str) -> ActiveLockout:
        await self._accounts.get(account_id)
        now = self._clock.now()
        existing = await self._repos.risk.active_lockout(account_id, now)
        if existing is not None and existing.reason == KILL_SWITCH_REASON:
            return existing
        return await self._open_lockout(account_id, KILL_SWITCH_REASON, None, now)

    async def acknowledge(self, account_id: str) -> str:
        """The human saw it. Clears the active lockout (and stamps any expired one); returns what was cleared."""
        now = self._clock.now()
        active = await self._repos.risk.active_lockout(account_id, now)
        if active is None:
            raise NotFound("no active lockout to acknowledge", code="no_active_lockout")
        if active.until is not None:
            raise Conflict(
                "a timed pause ends by itself: there is nothing to acknowledge", code="pause_not_acknowledgeable"
            )
        await self._repos.risk.acknowledge(account_id, active.lockout_id, now)
        await self._events.publish(
            LockoutAcknowledged(account_id=account_id, lockout_id=active.lockout_id, acknowledged_at=now)
        )
        by = cleared_by_for_ack(active.reason)
        await self._repos.risk.clear_lockout(account_id, by, now)
        await self._events.publish(LockoutCleared(account_id=account_id, lockout_id=active.lockout_id, cleared_by=by))
        await self.evaluate(account_id)
        return active.lockout_id

    async def _on_position_opened(self, event: PositionOpened) -> None:
        """T02c: a position that opened while a lockout was in force is a fact worth shouting about."""
        if event.account_id is None or event.reconstructed:
            return
        try:
            windows = await self._repos.risk.lockout_history(event.account_id, event.opened_at)
        except Unavailable:
            return
        for window in windows:
            covers = (window.cleared_at is None or window.cleared_at > event.opened_at) and (
                window.until is None or window.until > event.opened_at
            )
            if covers:
                await self._events.publish(
                    LockoutViolated(
                        account_id=event.account_id,
                        broker_position_id=event.position_id,
                        symbol=event.symbol,
                        side=event.side,
                        lockout_id=window.lockout_id,
                        lockout_reason=window.reason,
                        opened_at=event.opened_at,
                    )
                )
                return

    # ------------------------------------------------------------------------------------------ questions
    async def can_i_trade(self, account_id: str, symbol: str | None = None) -> CanITradeResult:
        built = await self._build(account_id, symbol=symbol)
        result = can_i_trade(built.context, symbol)
        reasons = _with_problems(result.reasons, built.problems)
        return result.model_copy(update={"reasons": reasons, "decision": "DENIED" if reasons else "ALLOWED"})

    async def review(self, intent: TradeIntent) -> RiskDecision:
        """Review one intent. Always returns a decision, approved or not, and has *persisted* it before returning."""
        account = await self._accounts.effective(intent.account_id)
        built = await self._build(intent.account_id, symbol=intent.symbol)
        spec = await self._market.require_spec(intent.account_id, intent.symbol)
        tick = self._market.tick(intent.account_id, intent.symbol)
        limits = account.execution_profile.limits
        review = IntentReview(
            spec=spec,
            spread=tick.spread if tick else None,
            commission_per_lot_round_trip=limits.commission_per_lot_round_trip,
            cost_threshold=limits.cost_threshold,
            max_volume_per_order=account.risk_profile.positions.max_volume_per_order,
        )
        decision = decide(built.context, intent, review)
        if built.problems and decision.approved:
            decision = decision.model_copy(
                update={
                    "approved": False,
                    "approved_volume": None,
                    "sizing": None,
                    "reasons": _with_problems(decision.reasons, built.problems),
                }
            )
        await self._repos.risk.record_decision(decision)
        event: RiskApproved | RiskRejected = (
            RiskApproved(account_id=intent.account_id, correlation_id=intent.intent_id, decision=decision)
            if decision.approved
            else RiskRejected(account_id=intent.account_id, correlation_id=intent.intent_id, decision=decision)
        )
        await self._events.publish(event)
        return decision

    async def enrich(self, snapshot: AccountSnapshot, positions: list[Position]) -> AccountSnapshot:
        """Complete the account snapshot with what only the risk engine knows (day's P&L, drawdown, open risk)."""
        account = await self._accounts.effective(snapshot.account_id)
        cache = self._cache.get(snapshot.account_id)
        day_start = cache.day_start_equity if cache else None
        session = self._accounts.session(snapshot.account_id)
        if day_start is None and session is not None:
            try:
                today = await self._today(account, session.client.offset_known, snapshot, positions, self._clock.now())
                day_start = today.day_start_equity
            except Unavailable:
                day_start = None  # unknown stays unknown
        specs = self._market.specs(snapshot.account_id)
        report = open_risk(positions, specs, snapshot.balance)
        update: dict[str, float] = {"open_risk_percent": report.percent}
        if day_start is not None and day_start > 0:
            update["daily_pnl"] = round(snapshot.equity - day_start, 2)
            update["daily_drawdown_percent"] = round(max(0.0, (day_start - snapshot.equity) / day_start * 100), 2)
        reference = account.risk_profile.drawdown.reference_balance or snapshot.balance
        if reference > 0:
            update["total_drawdown_percent"] = round(max(0.0, (reference - snapshot.equity) / reference * 100), 2)
        return snapshot.model_copy(update=update)


_HARD_GATES = frozenset({"gate-daily-loss", "gate-total-dd", "gate-max-trades", CONSECUTIVE_LOSS_GATE_ID})


def _with_problems(reasons: list[str], problems: list[str]) -> list[str]:
    """Plumbing problems are reasons too: ``system_degraded`` is what the strategy and the cockpit switch on."""
    return [*reasons, "system_degraded"] if problems and "system_degraded" not in reasons else reasons


__all__ = ["CONSECUTIVE_LOSS_REASON", "AgentDirectory", "CalendarSource", "RiskService"]
