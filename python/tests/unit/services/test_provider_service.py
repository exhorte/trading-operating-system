"""ProviderService: identification from the terminal's facts, the provider's loss references kept across restarts, the request count,
and what the Risk Engine is handed (ADR 0036). Simulated terminals — nothing here is a reading of a real provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest

from tests.support.builders import NOW, make_command
from tests.support.harness import Harness
from tests.unit.services.test_accounts_service import exness, ftmo, service
from trading_os.domain.accounts.models import AccountType, Environment, FtmoChallenge, Provider
from trading_os.domain.execution.commands import CommandState
from trading_os.domain.providers.identity import Confidence, IdentityBlocker
from trading_os.domain.providers.loss_floors import (
    DAILY_LOSS_BREACHED,
    EQUITY_UNKNOWN,
    MAX_REFERENCE_INCOMPLETE,
    day_start_utc,
)
from trading_os.domain.providers.rules import ProviderProduct
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.mt5.fake import FakeMt5
from trading_os.services.accounts import AccountCreate, AccountService
from trading_os.services.market_data import MarketDataService
from trading_os.services.positions import PositionService
from trading_os.services.providers import ProviderService
from trading_os.shared.errors import Unavailable

pytestmark = pytest.mark.db

PRAGUE = "Europe/Prague"
TODAY = date(2026, 10, 7)  # NOW is 2026-10-07 12:00 UTC = 14:00 in Prague (CEST)
BALANCE_DEAL, DEAL_OUT, SELL = 2, 1, 1


@dataclass
class Rig:
    h: Harness
    accounts: AccountService
    market: MarketDataService
    positions: PositionService
    providers: ProviderService
    terminal: FakeMt5
    account_id: str
    login: int

    def new_service(self) -> ProviderService:
        """A fresh service over the same database: what a restart of the core is."""
        return ProviderService(
            accounts=self.accounts, positions=self.positions, market=self.market, repos=self.h.repos, clock=self.h.clock
        )

    def set_balance(self, balance: float) -> None:
        self.terminal.accounts[self.login].balance = balance

    async def refresh(self) -> None:
        await self.positions.poll(self.account_id)

    def at(self, hour: int, *, day: int = 7, month: int = 10) -> int:
        return int(datetime(2026, month, day, hour, 0, tzinfo=UTC).timestamp())  # the simulated broker clock is UTC


async def make_rig(h: Harness, create: AccountCreate | None = None, *, connect: bool = True) -> Rig:
    accounts = service(h)
    spec = create or exness()
    created = await accounts.create(spec)
    if connect:
        await accounts.connect(created.id)
    market = MarketDataService(accounts=accounts, repos=h.repos, events=h.events, clock=h.clock)
    positions = PositionService(accounts=accounts, repos=h.repos, events=h.events, clock=h.clock, market=market)
    providers = ProviderService(accounts=accounts, positions=positions, market=market, repos=h.repos, clock=h.clock)
    if connect:
        await market.prepare(created.id)
        await market.poll_ticks(created.id)
        await positions.poll(created.id)
    return Rig(h, accounts, market, positions, providers, h.terminal(created), created.id, created.login)


def funded(challenge_type: str = "2-step", login: int = 3_000_003) -> AccountCreate:
    return AccountCreate(
        name="FTMO account",
        provider=Provider.FTMO,
        account_type=AccountType.PROP_FUNDED,
        login=login,
        server="FTMO-Server3",
        environment=Environment.LIVE,
        challenge=FtmoChallenge.model_validate({"type": challenge_type, "accountSize": 10_000, "phase": "funded"}),
        terminal_path=f"C:/MT5/ftmo-{login}",
    )


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


# ------------------------------------------------------------------------------------------------------------ identification


async def test_a_connected_exness_demo_is_identified_from_what_its_terminal_says(h: Harness) -> None:
    rig = await make_rig(h)
    result = await rig.providers.identify(rig.account_id)
    assert result.provider is Provider.EXNESS and result.provider_confidence is Confidence.CONFIRMED
    assert result.broker_product is ProviderProduct.EXNESS_STANDARD  # the suffix the terminal's symbols really carry
    assert result.account_mode == "DEMO" and result.executable, result.summary


async def test_an_ftmo_account_is_identified_by_its_names_and_its_declared_product(h: Harness) -> None:
    rig = await make_rig(h, ftmo())
    result = await rig.providers.identify(rig.account_id)
    assert result.provider is Provider.FTMO and result.rules_product is ProviderProduct.FTMO_CHALLENGE_2STEP
    assert result.account_mode == "SIMULATED" and result.executable, result.summary


async def test_an_account_that_is_not_connected_cannot_be_identified_and_is_not_executable(h: Harness) -> None:
    rig = await make_rig(h, connect=False)
    result = await rig.providers.identify(rig.account_id)
    assert result.provider is None and not result.executable
    assert (
        IdentityBlocker.PROVIDER_NOT_IDENTIFIED in result.blockers and IdentityBlocker.FACTS_MISSING in result.blockers
    )


async def test_a_declared_demo_whose_terminal_turns_out_real_is_caught_at_the_next_refresh(h: Harness) -> None:
    rig = await make_rig(h)
    assert (await rig.providers.identify(rig.account_id)).executable
    rig.terminal.accounts[rig.login].trade_mode = 2  # the terminal now says REAL
    assert (await rig.providers.identify(rig.account_id)).executable  # still inside the cache
    h.clock.advance(minutes=6)
    result = await rig.providers.identify(rig.account_id)
    assert IdentityBlocker.ENVIRONMENT_MISMATCH in result.blockers and not result.executable


async def test_a_terminal_of_another_company_than_the_declared_provider_is_not_obeyed(h: Harness) -> None:
    rig = await make_rig(h)
    rig.terminal.accounts[rig.login].company = "Some Other Broker Ltd"
    h.clock.advance(minutes=6)
    result = await rig.providers.identify(rig.account_id)
    assert not result.executable  # the server still says Exness, but the account and the terminal no longer do


async def test_the_profile_puts_the_declaration_next_to_the_observation(h: Harness) -> None:
    rig = await make_rig(h)
    profile = await rig.providers.profile(rig.account_id)
    assert (profile.declared_provider, profile.provider, profile.account_mode) == ("EXNESS", "EXNESS", "DEMO")
    assert profile.broker == "Exness Technologies Ltd" and profile.currency == "USD" and profile.leverage == 500
    assert profile.initial_capital == 10_000 and profile.balance == 10_000 and profile.equity == 10_000
    assert profile.last_synchronized_at is not None and profile.rule_set_id == "EXNESS_STANDARD@2026-11-03"
    assert profile.permissions.terminal_trade_allowed is True and profile.permissions.account_trading_enabled
    assert profile.identification.executable and profile.problems == ()


async def test_an_unconnected_profile_has_no_figures_not_zeros(h: Harness) -> None:
    rig = await make_rig(h, connect=False)
    profile = await rig.providers.profile(rig.account_id)
    assert profile.balance is None and profile.equity is None and profile.last_synchronized_at is None
    assert profile.problems


# ------------------------------------------------------------------------------------------------------- loss references


async def test_the_daily_reference_is_rebuilt_from_the_deals_since_midnight_not_taken_from_the_balance_of_the_moment(
    h: Harness,
) -> None:
    rig = await make_rig(h, ftmo())
    # A loss of 200 was realised this morning: the balance is 9 800 now and was 10 000 at 00:00 Prague.
    rig.terminal.add_deal(
        position_id=1,
        symbol="EURUSD",
        side=SELL,
        entry=DEAL_OUT,
        volume=0.1,
        price=1.1,
        server_time=rig.at(8),
        profit=-200.0,
    )
    rig.set_balance(9_800.0)
    await rig.refresh()
    state = await rig.providers.loss_state_of(rig.account_id)
    assert state.daily_reference_balance == 10_000.0, state
    assert state.daily_floor == 9_500.0 and state.timezone == PRAGUE
    stored = await h.repos.providers.get(rig.account_id, TODAY)
    assert stored is not None and stored.source == "reconstructed" and stored.reference_balance == 10_000.0


async def test_a_reference_survives_a_restart_and_a_fall_of_the_balance(h: Harness) -> None:
    rig = await make_rig(h, ftmo())
    first = await rig.providers.loss_state_of(rig.account_id)
    assert first.daily_reference_balance == 10_000.0
    rig.set_balance(9_400.0)  # a loss, then the core restarts: a new service, no memory
    await rig.refresh()
    restarted = rig.new_service()
    again = await restarted.loss_state_of(rig.account_id)
    assert again.daily_reference_balance == 10_000.0  # not 9 400: the limit was not reset
    assert again.status == "breached" and DAILY_LOSS_BREACHED in again.reasons  # equity 9 400 < floor 9 500


async def test_the_new_day_starts_with_the_balance_seen_at_its_first_minute(h: Harness) -> None:
    rig = await make_rig(h, ftmo())
    await rig.providers.loss_state_of(rig.account_id)
    rig.set_balance(10_150.0)
    h.clock.set(day_start_utc(date(2026, 10, 8), PRAGUE) + timedelta(seconds=30))
    await rig.market.poll_ticks(rig.account_id)
    await rig.refresh()
    state = await rig.providers.loss_state_of(rig.account_id)
    stored = await h.repos.providers.get(rig.account_id, date(2026, 10, 8))
    assert state.daily_reference_balance == 10_150.0 and stored is not None and stored.source == "observed"
    assert (await h.repos.providers.get(rig.account_id, TODAY)).reference_balance == 10_000.0  # type: ignore[union-attr]


async def test_without_a_snapshot_the_floors_are_unknown_not_guessed(h: Harness) -> None:
    rig = await make_rig(h, ftmo(), connect=False)
    state = await rig.providers.loss_state_of(rig.account_id)
    assert state.status == "unknown" and EQUITY_UNKNOWN in state.reasons and state.blocks_entries


async def test_an_unreadable_history_leaves_the_reference_unknown_and_the_database_untouched(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await make_rig(h, ftmo())
    session = rig.accounts.session(rig.account_id)
    assert session is not None

    async def broken(*args: object, **kwargs: object) -> list[object]:
        raise Unavailable("history unreadable", code="mt5_unavailable")

    monkeypatch.setattr(session.client, "deals_between", broken)
    state = await rig.providers.loss_state_of(rig.account_id)
    assert state.status == "unknown" and state.daily_floor is None
    assert await h.repos.providers.get(rig.account_id, TODAY) is None  # nothing invented was written


async def test_the_trailing_maximum_is_rebuilt_from_the_whole_history_and_kept(h: Harness) -> None:
    one_step = await make_rig(h, funded("1-step", login=3_000_004))
    terminal, login = one_step.terminal, one_step.login
    terminal.add_deal(
        position_id=0,
        symbol="",
        side=BALANCE_DEAL,
        entry=0,
        volume=0,
        price=0,
        server_time=one_step.at(10, day=27, month=9),
        profit=10_000.0,
    )
    terminal.add_deal(
        position_id=1,
        symbol="EURUSD",
        side=SELL,
        entry=DEAL_OUT,
        volume=0.1,
        price=1.1,
        server_time=one_step.at(10, day=2),
        profit=500.0,
    )
    one_step.set_balance(10_500.0)
    await one_step.refresh()
    state = await one_step.providers.loss_state_of(one_step.account_id)
    assert (state.max_reference_balance, state.max_floor) == (
        10_500.0,
        9_500.0,
    )  # highest 00:00 balance, − 10 % of 10 000
    assert (state.daily_reference_balance, state.daily_floor) == (10_500.0, 10_200.0)  # 3 % for a 1-Step
    assert state.status == "ok" and login
    stored = await h.repos.providers.all(one_step.account_id)
    assert stored[0].local_date == date(2026, 9, 27) and stored[-1].local_date == TODAY and len(stored) == 11
    assert {item.source for item in stored} == {"reconstructed"}
    again = await one_step.new_service().loss_state_of(one_step.account_id)  # after a restart: the same floors
    assert (again.max_floor, again.daily_floor) == (9_500.0, 10_200.0)


async def test_a_trailing_maximum_with_an_unreadable_history_is_incomplete_and_blocks(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await make_rig(h, funded("1-step", login=3_000_005))
    session = rig.accounts.session(rig.account_id)
    assert session is not None
    original = session.client.deals_between
    calls = {"n": 0}

    async def first_ok_then_broken(start: datetime, end: datetime) -> list[object]:
        calls["n"] += 1
        if calls["n"] == 1:  # today's reference rebuilt from the deals since midnight
            return await original(start, end)
        raise Unavailable("history unreadable", code="mt5_unavailable")

    monkeypatch.setattr(session.client, "deals_between", first_ok_then_broken)
    state = await rig.providers.loss_state_of(rig.account_id)
    assert state.status == "unknown" and MAX_REFERENCE_INCOMPLETE in state.reasons
    assert state.daily_floor == 10_000.0 - 300.0  # what is known stays known
    assert state.max_floor is None


# ------------------------------------------------------------------------------------------------------- request budget


async def test_the_days_requests_are_the_commands_that_reached_the_server(h: Harness) -> None:
    rig = await make_rig(h, funded())
    sent = NOW + timedelta(minutes=1)
    for index, state in enumerate(
        (
            CommandState.EXECUTED,
            CommandState.ACKNOWLEDGED,
            CommandState.SIMULATED,
            CommandState.REJECTED,
            CommandState.PENDING,
        )
    ):
        command = make_command(f"cmd-{index}", account_id=rig.account_id, state=state)
        command = command.model_copy(update={"sent_at": sent if state is not CommandState.PENDING else None})
        await h.repos.execution.insert(command, NOW)
    context = await rig.providers.context(rig.account_id)
    assert context.requests is not None
    assert (context.requests.limit, context.requests.used) == (
        2_000,
        2,
    )  # executed + acknowledged; the rest never reached it


async def test_a_product_without_a_request_ceiling_has_no_budget_to_exhaust(h: Harness) -> None:
    rig = await make_rig(h)
    context = await rig.providers.context(rig.account_id)
    assert context.requests is not None and context.requests.status == "not_applicable"


# ------------------------------------------------------------------------------------------------- what the engine is handed


async def test_a_funded_standard_account_without_a_news_source_refuses_entries_on_purpose(h: Harness) -> None:
    rig = await make_rig(h, funded())
    context = await rig.providers.context(rig.account_id, symbol="EURUSD")
    assert (
        context.news is not None
        and context.news.status == "unknown"
        and context.news.reason == "provider_news_calendar_unknown"
    )
    assert context.overnight is not None and context.overnight.status == "unknown"


async def test_an_evaluation_phase_and_a_broker_account_carry_neither_restriction(h: Harness) -> None:
    for create in (ftmo(), exness(login=1_000_009)):
        rig = await make_rig(h, create)
        context = await rig.providers.context(
            rig.account_id, symbol="EURUSD" if create.provider is Provider.FTMO else "EURUSDm"
        )
        assert context.news is not None and context.news.status == "not_applicable"
        assert context.overnight is not None and context.overnight.status == "not_applicable"


async def test_the_context_carries_identity_rules_and_loss_together(h: Harness) -> None:
    rig = await make_rig(h, ftmo())
    context = await rig.providers.context(rig.account_id)
    assert context.identification.executable and context.rule_set is not None
    assert context.rule_set.rule_set_id == "FTMO_CHALLENGE_2STEP@2026-11-02"
    assert context.loss is not None and context.loss.status == "ok"


async def test_the_effective_policy_shows_the_traders_value_next_to_the_providers(h: Harness) -> None:
    rig = await make_rig(h, funded("1-step", login=3_000_006))
    policy = await rig.providers.effective_policy(rig.account_id)
    daily = policy.limit("daily_loss_percent")
    assert daily is not None and daily.value == 3.0
    assert {(candidate.source.value, candidate.value) for candidate in daily.candidates} == {
        ("personal", 5.0),
        ("product", 3.0),
    }
    assert policy.executable and policy.rule_set_id == "FTMO_ACCOUNT_1STEP@2026-11-02"
