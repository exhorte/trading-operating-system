"""The provider side of an account as a service (ADR 0036): who it is, what its contract allows, and where the day's references are.

Three jobs, none of which decides a trade — the Risk Engine does, with what this service hands it:

* **identify** the account from the terminal's own facts (cached a few minutes, refreshed when the login changes), never from the
  stored declaration alone;
* keep the provider's **loss references** — the balance at 00:00 of each provider day. They are persisted append-only, rebuilt from the
  broker's deal history when the core was not there to see them (a balance does not depend on floating P/L, so a position open across
  midnight does not prevent it), and **never** derived from the balance of the moment. When a reference cannot be established, the state
  is ``unknown`` and the Risk Engine refuses entries;
* count the day's **requests** against the provider's ceiling.

Everything unreadable (terminal, history, database) makes the answer ``unknown``, which blocks.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from trading_os.domain.accounts.discovery import INSTRUMENTS, broker_name_of
from trading_os.domain.accounts.models import Account, AccountSnapshot
from trading_os.domain.execution.commands import CommandState
from trading_os.domain.market.instrument import InstrumentSpecification
from trading_os.domain.providers.commission import CommissionDeal, CommissionReading, resolve_commission
from trading_os.domain.providers.context import ProviderContext
from trading_os.domain.providers.identity import AccountIdentification, IdentityFacts, identify_account
from trading_os.domain.providers.loss_floors import (
    CashFlow,
    LossReference,
    ProviderLossState,
    day_start_utc,
    evaluate_loss_state,
    local_day,
    missing_days,
    reference_from_flows,
)
from trading_os.domain.providers.profile import AccountProfile, assemble_profile
from trading_os.domain.providers.restrictions import (
    RequestBudget,
    RestrictedEvent,
    evaluate_entry_before_break,
    evaluate_news_restriction,
    evaluate_request_budget,
)
from trading_os.domain.providers.rules import LossMethod, ProviderRuleSet, rule_set_for
from trading_os.domain.risk.dynamic_risk import RiskAllowance
from trading_os.domain.risk.effective import EffectiveRiskPolicy, resolve_effective_policy
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.infrastructure.mt5.client import TRADE_MODES
from trading_os.infrastructure.mt5.protocol import WorkerError
from trading_os.services.accounts import AccountService, AccountSession
from trading_os.services.market_data import MarketDataService
from trading_os.services.positions import PositionService
from trading_os.shared.errors import Unavailable
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

IDENTITY_TTL = timedelta(minutes=5)
DAY_JUST_STARTED = timedelta(minutes=2)  # within this, the balance seen now *is* the day's reference
REQUEST_COUNT_TTL = timedelta(seconds=10)
COMMISSION_TTL = timedelta(minutes=10)
COMMISSION_LOOKBACK = timedelta(days=90)
_DEAL_BUY, _DEAL_SELL = (
    0,
    1,
)  # MT5 DEAL_TYPE_*: only trades carry a commission worth reading (balance operations do not)
_DEAL_ENTRY = {0: "in", 1: "out", 3: "out"}  # IN, OUT, OUT_BY (a reversal, INOUT, is left out)
HISTORY_START = datetime(2000, 1, 1, tzinfo=UTC)

# A command that never reached the trade server is not a request to it.
_NOT_REQUESTS = frozenset({CommandState.SIMULATED, CommandState.REJECTED})

# Where the provider's restricted-news calendar would come from: ``(events, currencies the calendar is complete for)``, or ``None`` when
# nothing feeds it. Nothing does yet — a generic economic calendar may not authorise an action (ADR 0036) — so a product with a news
# rule refuses entries with ``provider_news_calendar_unknown``, on purpose.
RestrictedCalendar = Callable[[], tuple[Sequence[RestrictedEvent], frozenset[str]] | None]


@dataclass
class _Identified:
    at: datetime
    login: int
    value: AccountIdentification


@dataclass
class _DayReferences:
    day: date
    daily: LossReference | None
    references: list[LossReference]
    complete: bool
    first_day: date | None = None


class ProviderService:
    def __init__(
        self,
        *,
        accounts: AccountService,
        positions: PositionService,
        market: MarketDataService,
        repos: Repositories,
        clock: Clock,
        restricted_calendar: RestrictedCalendar = lambda: None,
    ) -> None:
        self._accounts = accounts
        self._positions = positions
        self._market = market
        self._repos = repos
        self._clock = clock
        self._restricted_calendar = restricted_calendar
        self._identity: dict[str, _Identified] = {}
        self._days: dict[str, _DayReferences] = {}
        self._requests: dict[str, tuple[datetime, int | None]] = {}
        self._commission_read: dict[str, datetime] = {}

    def forget(self, account_id: str) -> None:
        """The account disconnected: nothing read from its terminal outlives the link. The persisted references stay, by design."""
        self._identity.pop(account_id, None)
        self._days.pop(account_id, None)
        self._requests.pop(account_id, None)
        self._commission_read.pop(account_id, None)
        self._accounts.set_commission(account_id, None)

    # ------------------------------------------------------------------------------------------ identification
    async def identify(self, account_id: str) -> AccountIdentification:
        account = await self._accounts.effective(account_id)
        session = self._accounts.session(account_id)
        now = self._clock.now()
        cached = self._identity.get(account_id)
        if (
            cached is not None
            and session is not None
            and cached.login == session.info.login
            and now - cached.at < IDENTITY_TTL
        ):
            return cached.value
        facts = await self._facts(account, session, now)
        value = identify_account(facts)
        if session is not None and facts.server is not None:
            self._identity[account_id] = _Identified(at=now, login=session.info.login, value=value)
        return value

    async def _facts(self, account: Account, session: AccountSession | None, now: datetime) -> IdentityFacts:
        declared = {
            "declared_provider": account.provider,
            "declared_environment": account.environment,
            "declared_account_type": account.account_type,
            "challenge": account.trading_rules.challenge,
        }
        if session is None:
            return IdentityFacts(**declared)
        try:
            info = await session.client.account_info()
            terminal = await session.client.terminal_info()
            names = await session.client.symbol_names()
        except (WorkerError, Unavailable) as error:
            logger.warning("identification: the terminal could not be read: %s", error)
            return IdentityFacts(**declared)
        spellings = {c: n for c in INSTRUMENTS if (n := broker_name_of(c, names)) is not None}
        suffixes = tuple(sorted({name[len(canonical) :] for canonical, name in spellings.items()}))
        return IdentityFacts(
            login=info.login,
            server=info.server or None,
            company=info.company or None,
            terminal_company=terminal.company or None,
            trade_mode=TRADE_MODES.get(info.trade_mode, "unknown"),
            currency=info.currency or None,
            leverage=info.leverage or None,
            observed_suffixes=suffixes,
            observed_at=now,
            **declared,
        )

    # ------------------------------------------------------------------------------------------ loss references
    async def loss_state(
        self, account: Account, rule_set: ProviderRuleSet | None, snapshot: AccountSnapshot | None, now: datetime
    ) -> ProviderLossState:
        initial = account.risk_profile.drawdown.reference_balance
        equity = snapshot.equity if snapshot is not None else None
        if rule_set is None or not rule_set.requires_loss_references:
            return evaluate_loss_state(rule_set, initial_capital=initial, equity=equity, now=now, daily_reference=None)
        references = await self._references(account, rule_set, snapshot, now)
        return evaluate_loss_state(
            rule_set,
            initial_capital=initial,
            equity=equity,
            now=now,
            daily_reference=references.daily,
            references=references.references,
            references_complete=references.complete,
        )

    async def _references(
        self, account: Account, rule_set: ProviderRuleSet, snapshot: AccountSnapshot | None, now: datetime
    ) -> _DayReferences:
        assert rule_set.daily_loss is not None and rule_set.max_loss is not None
        timezone = rule_set.daily_loss.timezone
        today = local_day(now, timezone)
        cached = self._days.get(account.id)
        trailing = rule_set.max_loss.method is LossMethod.TRAILING_EOD_BALANCE
        if (
            cached is not None
            and cached.day == today
            and cached.daily is not None
            and (cached.complete or not trailing)
        ):
            return cached
        if snapshot is None:
            return _DayReferences(day=today, daily=None, references=[], complete=False)
        try:
            computed = await self._compute_references(account, rule_set, snapshot, now, today, trailing, cached)
        except Unavailable as error:
            logger.warning("provider references: the database is unavailable: %s", error)
            return _DayReferences(day=today, daily=None, references=[], complete=False)
        self._days[account.id] = computed
        return computed

    async def _compute_references(
        self,
        account: Account,
        rule_set: ProviderRuleSet,
        snapshot: AccountSnapshot,
        now: datetime,
        today: date,
        trailing: bool,
        previous: _DayReferences | None,
    ) -> _DayReferences:
        assert rule_set.daily_loss is not None
        timezone = rule_set.daily_loss.timezone
        stored = await self._repos.providers.all(account.id)
        by_day = {reference.local_date: reference for reference in stored}
        flows: list[CashFlow] | None = None
        flows_read = False

        async def read_flows() -> list[CashFlow] | None:
            nonlocal flows, flows_read
            if not flows_read:
                flows, flows_read = await self._flows(account.id, HISTORY_START, snapshot.observed_at), True
            return flows

        # --- today's reference: the one recorded, else observed if the day has just begun, else rebuilt from the deals since
        if today not in by_day:
            start = day_start_utc(today, timezone)
            created: LossReference | None = None
            if now - start <= DAY_JUST_STARTED:
                created = LossReference(
                    local_date=today,
                    timezone=timezone,
                    reference_balance=snapshot.balance,
                    recorded_at=now,
                    source="observed",
                    rule_set_id=rule_set.rule_set_id,
                )
            else:
                since_midnight = await self._flows(account.id, start, snapshot.observed_at)
                if since_midnight is not None:
                    created = reference_from_flows(
                        today,
                        timezone=timezone,
                        current_balance=snapshot.balance,
                        flows=since_midnight,
                        recorded_at=now,
                        rule_set_id=rule_set.rule_set_id,
                    )
            if created is not None:
                await self._repos.providers.record(account.id, created)
                by_day[today] = (await self._repos.providers.get(account.id, today)) or created

        first_day = previous.first_day if previous is not None else None
        complete = True
        if trailing:
            # The trailing maximum needs *every* midnight since the account began. The first day comes from the full history, read once
            # per process; the days that are missing are rebuilt from it and recorded. If the history cannot be read, it stays incomplete.
            if first_day is None:
                everything = await read_flows()
                if everything is not None:
                    first_day = local_day(min((flow.at for flow in everything), default=now), timezone)
            if first_day is None:
                complete = False
            else:
                gaps = missing_days(list(by_day.values()), first_day, today)
                if gaps:
                    everything = await read_flows()
                    if everything is None:
                        complete = False
                    else:
                        rebuilt = [
                            reference_from_flows(
                                day,
                                timezone=timezone,
                                current_balance=snapshot.balance,
                                flows=everything,
                                recorded_at=now,
                                rule_set_id=rule_set.rule_set_id,
                            )
                            for day in gaps
                        ]
                        await self._repos.providers.record_many(account.id, rebuilt)
                        by_day = {ref.local_date: ref for ref in await self._repos.providers.all(account.id)}
                        complete = not missing_days(list(by_day.values()), first_day, today)
        return _DayReferences(
            day=today,
            daily=by_day.get(today),
            references=sorted(by_day.values(), key=lambda reference: reference.local_date),
            complete=complete,
            first_day=first_day,
        )

    async def _flows(self, account_id: str, start: datetime, end: datetime) -> list[CashFlow] | None:
        """Everything that moved the balance in ``(start, end]``, from the broker's deal history; ``None`` when it cannot be read.
        Deal times are the broker's clock: they are converted with the offset measured on the terminal, and with no offset measured there
        is nothing to convert with (``None``, never a guess)."""
        session = self._accounts.session(account_id)
        if session is None or not session.client.offset_known:
            return None
        try:
            deals = await session.client.deals_between(start, end + timedelta(days=1))
        except (WorkerError, Unavailable) as error:
            logger.warning("provider references: the deal history could not be read: %s", error)
            return None
        flows = [
            CashFlow(at=session.client.to_utc(float(deal.time)), amount=deal.profit + deal.commission + deal.swap)
            for deal in deals
        ]
        return [flow for flow in flows if flow.at <= end]

    # ------------------------------------------------------------------------------------------ requests
    async def request_budget(self, account_id: str, rule_set: ProviderRuleSet | None, now: datetime) -> RequestBudget:
        if rule_set is None or rule_set.max_requests_per_day is None:
            return evaluate_request_budget(rule_set, used_today=0)
        timezone = rule_set.daily_loss.timezone if rule_set.daily_loss is not None else "UTC"
        cached = self._requests.get(account_id)
        if cached is None or now - cached[0] >= REQUEST_COUNT_TTL:
            start = day_start_utc(local_day(now, timezone), timezone)
            try:
                commands = await self._repos.execution.created_since(account_id, start)
                used: int | None = sum(
                    1 for command in commands if command.sent_at is not None and command.state not in _NOT_REQUESTS
                )
            except Unavailable:
                used = None
            cached = (now, used)
            self._requests[account_id] = cached
        return evaluate_request_budget(rule_set, used_today=cached[1])

    # ------------------------------------------------------------------------------------------ commission
    async def refresh_commission(self, account_id: str) -> CommissionReading:
        """The commission this account pays, from its own closed positions when it has some, else the contract's documented figure, else
        the trader's configured assumption — and hand it to the account service, which puts it in the effective rules (ADR 0036)."""
        now = self._clock.now()
        known = self._accounts.commission(account_id)
        read = self._commission_read.get(account_id)
        if known is not None and read is not None and now - read < COMMISSION_TTL:
            return known
        identification = await self.identify(account_id)
        rule_set = rule_set_for(identification.rules_product)
        # The configured figure is the trader's own, read from the ledger: never the effective rules, which already carry the last reading.
        configured = (
            await self._accounts.resolved_rules(account_id)
        ).execution_profile.limits.commission_per_lot_round_trip
        # The carrier's contract decides what is documented about *its* commission; a rehearsed contract (FTMO's rules on an Exness demo)
        # does not change what the broker charges.
        carrier = rule_set_for(identification.broker_product) if identification.rules_rehearsal else rule_set
        deals = await self._commission_deals(account_id, now)
        reading = resolve_commission(deals=deals, rule_set=carrier, configured=configured)
        self._accounts.set_commission(account_id, reading)
        if deals is not None:
            self._commission_read[account_id] = (
                now  # an unreadable history is retried at the next cycle, not trusted for ten minutes
            )
        return reading

    async def _commission_deals(self, account_id: str, now: datetime) -> list[CommissionDeal] | None:
        session = self._accounts.session(account_id)
        if session is None or not session.client.offset_known:
            return None
        try:
            deals = await session.client.deals_between(now - COMMISSION_LOOKBACK, now + timedelta(days=1))
        except (WorkerError, Unavailable) as error:
            logger.warning("commission: the deal history could not be read: %s", error)
            return None
        return [
            CommissionDeal(
                position_id=deal.position_id,
                entry=_DEAL_ENTRY[deal.entry],
                volume=deal.volume,
                commission=deal.commission,
            )
            for deal in deals
            if deal.type in (_DEAL_BUY, _DEAL_SELL) and deal.position_id and deal.entry in _DEAL_ENTRY
        ]

    # ------------------------------------------------------------------------------------------ what the Risk Engine reads
    async def context(self, account_id: str, *, symbol: str | None = None) -> ProviderContext:
        account = await self._accounts.effective(account_id)
        now = self._clock.now()
        identification = await self.identify(account_id)
        rule_set = rule_set_for(identification.rules_product)
        snapshot = self._positions.snapshot(account_id)
        await self.refresh_commission(account_id)
        loss = await self.loss_state(account, rule_set, snapshot, now)
        requests = await self.request_budget(account_id, rule_set, now)
        news = overnight = None
        if symbol is not None:
            spec = self._market.spec(account_id, symbol)
            calendar = self._restricted_calendar()
            news = evaluate_news_restriction(
                rule_set,
                now=now,
                symbol=symbol,
                base_currency=spec.currency_base if spec else None,
                profit_currency=spec.currency_profit if spec else None,
                action="open",
                events=calendar[0] if calendar else None,
                covered_currencies=calendar[1] if calendar else None,
            )
            overnight = evaluate_entry_before_break(rule_set, now=now, breaks=None)
        return ProviderContext(
            identification=identification,
            rule_set=rule_set,
            loss=loss,
            news=news,
            overnight=overnight,
            requests=requests,
        )

    # ------------------------------------------------------------------------------------------ read models
    async def profile(self, account_id: str) -> AccountProfile:
        account = await self._accounts.effective(account_id)
        identification = await self.identify(account_id)
        rule_set = rule_set_for(identification.rules_product)
        return assemble_profile(
            account,
            snapshot=self._positions.snapshot(account_id),
            identification=identification,
            rule_version=rule_set.version if rule_set else None,
            now=self._clock.now(),
            commission=self._accounts.commission(account_id),
        )

    async def effective_policy(
        self, account_id: str, *, symbol: str | None = None, live_allowance: RiskAllowance | None = None
    ) -> EffectiveRiskPolicy:
        personal = (await self._accounts.resolved_rules(account_id)).risk_profile
        account = await self._accounts.effective(account_id)
        identification = await self.identify(account_id)
        spec = self._market.spec(account_id, symbol) if symbol else None
        return resolve_effective_policy(
            account_id=account_id,
            personal=personal,
            rule_set=rule_set_for(identification.rules_product),
            identification=identification,
            now=self._clock.now(),
            spec=spec if isinstance(spec, InstrumentSpecification) else None,
            spread_cap=account.execution_profile.limits.max_spread_by_symbol.get(symbol or ""),
            live_allowance=live_allowance,
            commission=self._accounts.commission(account_id),
        )

    async def loss_state_of(self, account_id: str) -> ProviderLossState:
        """For the cockpit: the floors and the room left, computed with the same references the Risk Engine uses."""
        account = await self._accounts.effective(account_id)
        identification = await self.identify(account_id)
        return await self.loss_state(
            account, rule_set_for(identification.rules_product), self._positions.snapshot(account_id), self._clock.now()
        )


__all__ = ["ProviderService", "RestrictedCalendar"]
