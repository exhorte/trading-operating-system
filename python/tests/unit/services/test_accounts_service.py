"""AccountService against a real database and simulated terminals: registry, connections, the single active account,
switch/disconnect guards, the trading switch, and the anti-tilt rules ledger."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from pydantic import SecretStr

from tests.support.harness import Harness
from trading_os.domain.accounts.discovery import DEAL_TYPE_BALANCE
from trading_os.domain.accounts.models import AccountStatus, AccountType, Environment, FtmoChallenge, Provider
from trading_os.domain.events import (
    AccountArchived,
    AccountConnected,
    AccountCreated,
    AccountDisconnected,
    AccountErrored,
    AccountRulesChanged,
    AccountTradingToggled,
    ActiveAccountChanged,
)
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.mt5.client import ConnectFailed
from trading_os.infrastructure.mt5.fake import FakeAccount, FakeMt5
from trading_os.infrastructure.security.credentials import EnvCredentialStore
from trading_os.services.accounts import AccountCreate, AccountService
from trading_os.shared.errors import AccountMismatch, Conflict, ValidationFailed

pytestmark = pytest.mark.db


def service(h: Harness) -> AccountService:
    return AccountService(
        repos=h.repos, events=h.events, clock=h.clock, credentials=h.credentials, mt5_factory=h.mt5_factory
    )


def exness(login: int = 1_000_001, **extra: object) -> AccountCreate:
    fields: dict[str, object] = {
        "name": "Exness demo",
        "provider": Provider.EXNESS,
        "account_type": AccountType.DIRECT,
        "login": login,
        "server": "Exness-MT5Trial",
        "environment": Environment.DEMO,
        "reference_balance": 10_000,
        "terminal_path": f"C:/MT5/exness-{login}",
    }
    fields.update(extra)
    return AccountCreate.model_validate(fields)


def ftmo(login: int = 2_000_002) -> AccountCreate:
    return AccountCreate(
        name="FTMO challenge",
        provider=Provider.FTMO,
        account_type=AccountType.PROP_CHALLENGE,
        login=login,
        server="FTMO-Server3",
        environment=Environment.LIVE,
        challenge=FtmoChallenge(type="2-step", account_size=10_000, phase="challenge"),
        terminal_path=f"C:/MT5/ftmo-{login}",
    )


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def test_an_account_is_created_with_its_providers_default_rules(h: Harness) -> None:
    accounts = service(h)
    exn = await accounts.create(exness())
    prop = await accounts.create(ftmo())
    assert exn.id == "exness-1000001" and exn.symbol_suffix == "m" and exn.status is AccountStatus.DISCONNECTED
    assert exn.risk_profile.drawdown.reference_balance == 10_000
    assert prop.symbol_suffix == "" and prop.trading_rules.challenge is not None
    assert prop.risk_profile.drawdown.reference_balance == 10_000  # FTMO limits are a % of the challenge size
    assert [a.id for a in await accounts.accounts()] == ["exness-1000001", "ftmo-2000002"]
    assert [e.name for e in h.recorder.of(AccountCreated)] == ["Exness demo", "FTMO challenge"]


async def test_an_account_type_that_does_not_fit_the_provider_is_refused(h: Harness) -> None:
    with pytest.raises(ValidationFailed) as caught:
        await service(h).create(exness(account_type=AccountType.PROP_CHALLENGE))
    assert caught.value.code == "account_type_not_allowed"
    with pytest.raises(Conflict):
        accounts = service(h)
        await accounts.create(exness())
        await accounts.create(exness(name="same login again"))


async def test_the_connected_account_is_the_active_one_and_it_is_remembered(h: Harness) -> None:
    accounts = service(h)
    first = await accounts.create(exness())
    await accounts.create(ftmo())
    connected = await accounts.connect(first.id)
    assert connected.status is AccountStatus.CONNECTED
    assert accounts.active_account_id == first.id
    assert [e.current for e in h.recorder.of(ActiveAccountChanged)] == [first.id]
    assert {e.account_id for e in h.recorder.of(AccountConnected)} == {first.id}

    restarted = service(h)  # a new process: the active account comes back from the database
    await restarted.start()
    assert restarted.active_account_id == first.id


async def test_connecting_twice_is_idempotent_and_only_one_account_is_connected_at_a_time(h: Harness) -> None:
    accounts = service(h)
    first = await accounts.create(exness(terminal_path=None))
    other = await accounts.create(exness(login=3_000_003, terminal_path="C:/MT5/other"))  # even on its own terminal
    await accounts.connect(first.id)
    await accounts.connect(first.id)
    assert len(h.recorder.of(AccountConnected)) == 1
    with pytest.raises(Conflict) as caught:
        await accounts.connect(other.id)
    assert caught.value.code == "another_account_connected"
    assert caught.value.details["connectedAccountId"] == first.id
    assert not accounts.is_connected(other.id) and accounts.active_account_id == first.id


async def test_a_wrong_server_is_refused_and_remembered_as_an_error_until_fixed(h: Harness) -> None:
    accounts = service(h)
    created = await accounts.create(exness(server="Exness-Real"))
    h.terminal(created).accounts[created.login].server = "Exness-MT5Trial"  # the terminal is on another server
    with pytest.raises(AccountMismatch) as caught:
        await accounts.connect(created.id)
    assert caught.value.code == "server_mismatch"
    view = await accounts.get(created.id)
    assert view.status is AccountStatus.ERROR and "server" in (view.status_detail or "")
    assert not accounts.is_connected(created.id)
    assert h.recorder.of(AccountErrored)[0].code == "server_mismatch"


async def test_a_password_comes_from_the_store_or_the_call_and_never_leaks(
    h: Harness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    accounts = service(h)
    created = await accounts.create(exness(login=4_000_004, terminal_path="C:/MT5/pw"))
    password = f"pw-{created.login}"
    with pytest.raises(ConnectFailed) as wrong:
        await accounts.connect(created.id, SecretStr("not-the-password-xyz"))
    assert wrong.value.code == "login_failed" and "not-the-password-xyz" not in str(wrong.value)

    h.credentials = EnvCredentialStore()
    accounts = AccountService(
        repos=h.repos, events=h.events, clock=h.clock, credentials=h.credentials, mt5_factory=h.mt5_factory
    )
    monkeypatch.setenv(EnvCredentialStore.variable(created.id), password)
    await accounts.connect(created.id)  # the store supplies it
    assert accounts.is_connected(created.id)
    everything = repr(h.recorder.events) + caplog.text + repr(await accounts.accounts())
    assert password not in everything and "not-the-password-xyz" not in everything
    rows = await h.db.fetch_all("SELECT * FROM accounts")
    assert password not in repr(rows)


async def test_detaching_is_refused_while_a_guard_sees_risk_and_so_is_taking_another_account(h: Harness) -> None:
    accounts = service(h)
    a = await accounts.create(exness())
    b = await accounts.create(ftmo())
    await accounts.connect(a.id)

    async def guard(account_id: str) -> str | None:
        return "a position is open" if account_id == a.id else None

    accounts.add_guard(guard)
    with pytest.raises(Conflict) as disconnect:
        await accounts.disconnect(a.id)
    assert disconnect.value.code == "disconnect_refused" and disconnect.value.details["reasons"] == [
        "a position is open"
    ]
    with pytest.raises(Conflict) as other:  # b cannot come in while a holds risk — and a cannot leave
        await accounts.connect(b.id)
    assert other.value.code == "another_account_connected" and accounts.active_account_id == a.id

    forced = await accounts.disconnect(a.id, force=True)
    assert forced.status is AccountStatus.DISCONNECTED
    assert [e.reason for e in h.recorder.of(AccountDisconnected)] == ["user"]
    with pytest.raises(Conflict) as offline:
        await accounts.set_active(b.id)
    assert offline.value.code == "account_not_connected"


async def test_taking_another_account_means_detaching_the_first_and_the_new_one_becomes_active(h: Harness) -> None:
    accounts = service(h)
    a = await accounts.create(exness())
    b = await accounts.create(ftmo())
    await accounts.connect(a.id)
    await accounts.disconnect(a.id)  # nothing at risk: allowed
    await accounts.connect(b.id)
    assert accounts.active_account_id == b.id and not accounts.is_connected(a.id)
    assert [(e.previous, e.current) for e in h.recorder.of(ActiveAccountChanged)] == [(None, a.id), (a.id, b.id)]


async def test_a_lost_link_is_remembered_and_reconnect_restores_it(h: Harness) -> None:
    accounts = service(h)
    a = await accounts.create(exness())
    await accounts.connect(a.id)
    await accounts.mark_lost(a.id, "terminal stopped answering")
    view = await accounts.get(a.id)
    assert view.status is AccountStatus.ERROR and view.status_detail == "terminal stopped answering"
    assert h.recorder.of(AccountErrored)[-1].code == "connection_lost"
    again = await accounts.reconnect(a.id)
    assert again.status is AccountStatus.CONNECTED and accounts.is_connected(a.id)


async def test_the_trading_switch_is_persisted_and_announced(h: Harness) -> None:
    accounts = service(h)
    a = await accounts.create(exness())
    off = await accounts.set_trading_enabled(a.id, False)
    assert off.trading_enabled is False and (await service(h).get(a.id)).trading_enabled is False
    on = await accounts.set_trading_enabled(a.id, True)
    assert on.trading_enabled is True
    assert [e.enabled for e in h.recorder.of(AccountTradingToggled)] == [False, True]


async def test_an_account_cannot_be_archived_while_connected_and_loses_the_active_flag(h: Harness) -> None:
    accounts = service(h)
    a = await accounts.create(exness())
    await accounts.connect(a.id)
    with pytest.raises(Conflict):
        await accounts.archive(a.id)
    await accounts.disconnect(a.id)
    await accounts.archive(a.id)
    assert await accounts.accounts() == [] and accounts.active_account_id is None
    assert h.recorder.of(AccountArchived)


# ------------------------------------------------------------------------------------------------------ discovery (ADR 0020)

DEMO_PATH = "C:/MT5/exness-demo"
DEMO_LOGIN, DEMO_SERVER, DEMO_PASSWORD = 123_456_789, "Exness-MT5Trial10", "pw-demo-only"


def demo_terminal(
    h: Harness, *, suffix: str = "m", company: str = "Exness Technologies Ltd", **account: object
) -> FakeMt5:
    """A terminal already logged into an Exness-looking demo account, as the trader leaves it."""
    terminal = FakeMt5.for_accounts(
        [FakeAccount(login=DEMO_LOGIN, server=DEMO_SERVER, password=DEMO_PASSWORD, company=company, **account)],  # type: ignore[arg-type]
        suffix=suffix,
        server_offset_minutes=h.server_offset_minutes,
        clock=lambda: h.clock.now().timestamp(),
    )
    h.terminals[DEMO_PATH] = terminal
    return terminal


async def test_discovery_reads_the_account_from_the_broker_and_registers_nothing(h: Harness) -> None:
    accounts = service(h)
    demo_terminal(h)
    found = await accounts.discover(login=DEMO_LOGIN, server=DEMO_SERVER, terminal_path=DEMO_PATH)
    assert (found.login, found.server, found.company) == (DEMO_LOGIN, DEMO_SERVER, "Exness Technologies Ltd")
    assert (found.balance, found.equity, found.currency, found.leverage) == (10_000.0, 10_000.0, "USD", 500)
    assert found.trade_mode == "demo" and found.margin_mode == "hedging" and found.trade_allowed
    assert found.provider is Provider.EXNESS and found.environment is Environment.DEMO
    assert found.symbol_suffix == "m" and [s.broker_name for s in found.symbols] == ["EURUSDm", "XAUUSDm"]
    assert all(s.volume_min > 0 and s.contract_size > 0 and s.tradable for s in found.symbols)
    assert (found.open_positions, found.pending_orders) == (0, 0) and found.suggested_name == "Exness 123456789 démo"
    assert found.warnings == []
    # Read, not registered: no account, nothing active, no connection left behind.
    assert await accounts.accounts() == [] and accounts.active_account_id is None
    assert not h.recorder.of(AccountCreated) and not h.recorder.of(AccountConnected)


async def test_without_a_deposit_in_the_history_the_balance_is_only_a_proposal(h: Harness) -> None:
    demo_terminal(h, balance=9_640.25)
    found = await service(h).discover(login=DEMO_LOGIN, server=DEMO_SERVER, terminal_path=DEMO_PATH)
    assert (found.capital.amount, found.capital.source, found.capital.reliable) == (9_640.25, "current_balance", False)


async def test_the_first_deposit_in_the_brokers_history_is_the_initial_capital(h: Harness) -> None:
    terminal = demo_terminal(h, balance=9_640.25)
    first = int(h.clock.now().timestamp()) - 5 * 86_400
    terminal.add_deal(position_id=0, symbol="", side=DEAL_TYPE_BALANCE, entry=0, volume=0.0, price=0.0,
                      server_time=first, profit=10_000.0)  # fmt: skip
    terminal.add_deal(position_id=0, symbol="", side=DEAL_TYPE_BALANCE, entry=0, volume=0.0, price=0.0,
                      server_time=first + 3_600, profit=500.0)  # a later top-up is not the initial capital  # fmt: skip
    terminal.add_deal(position_id=0, symbol="", side=DEAL_TYPE_BALANCE, entry=0, volume=0.0, price=0.0,
                      server_time=first - 60, profit=-25.0)  # a withdrawal is not a deposit  # fmt: skip
    found = await service(h).discover(login=DEMO_LOGIN, server=DEMO_SERVER, terminal_path=DEMO_PATH)
    assert (found.capital.amount, found.capital.source, found.capital.reliable) == (10_000.0, "first_deposit", True)
    assert found.capital.at is not None and found.capital.at.timestamp() == first


async def test_a_wrong_password_is_refused_without_echoing_it_and_the_terminal_is_freed(h: Harness) -> None:
    accounts = service(h)
    demo_terminal(h)
    with pytest.raises(ConnectFailed) as refused:
        await accounts.discover(
            login=DEMO_LOGIN, server=DEMO_SERVER, password=SecretStr("S3NTINEL-wrong"), terminal_path=DEMO_PATH
        )
    assert refused.value.code == "login_failed" and "S3NTINEL-wrong" not in str(refused.value)
    found = await accounts.discover(  # the failed attempt left nothing behind: the right password works at once
        login=DEMO_LOGIN, server=DEMO_SERVER, password=SecretStr(DEMO_PASSWORD), terminal_path=DEMO_PATH
    )
    assert found.login == DEMO_LOGIN
    assert DEMO_PASSWORD not in found.model_dump_json()  # a password is never part of what comes back


async def test_discovery_refuses_while_another_account_is_connected(h: Harness) -> None:
    accounts = service(h)
    demo_terminal(h)
    created = await accounts.create(exness(login=DEMO_LOGIN, server=DEMO_SERVER, terminal_path=DEMO_PATH))
    await accounts.connect(created.id)
    with pytest.raises(Conflict) as refused:
        await accounts.discover(login=DEMO_LOGIN, server=DEMO_SERVER, terminal_path=DEMO_PATH)
    assert refused.value.code == "another_account_connected"


async def test_an_unknown_server_and_an_account_with_positions_are_warned_about(h: Harness) -> None:
    terminal = demo_terminal(h, company="Some Broker Ltd")
    terminal.add_position(identifier=7, symbol="EURUSDm", side=0, volume=0.1, price_open=1.08, sl=1.07,
                          opened_server_time=int(h.clock.now().timestamp()) - 60)  # fmt: skip
    found = await service(h).discover(login=DEMO_LOGIN, server="Exness-MT5Trial10", terminal_path=DEMO_PATH)
    assert found.open_positions == 1
    assert any("open position" in w for w in found.warnings)
    other = demo_terminal(h, company="Some Broker Ltd")
    other.accounts[DEMO_LOGIN].server = "Other-Server"
    unknown = await service(h).discover(login=DEMO_LOGIN, server="Other-Server", terminal_path=DEMO_PATH)
    assert unknown.provider is None and any("choose the provider" in w for w in unknown.warnings)


# ------------------------------------------------------------------------------------------------------ the FTMO profile on a demo


def ftmo_on_exness(**extra: object) -> AccountCreate:
    return exness(
        account_type=AccountType.PROP_CHALLENGE,
        rules_profile=Provider.FTMO,
        challenge=FtmoChallenge(type="2-step", account_size=10_000, phase="challenge"),
        **extra,
    )


async def test_an_exness_demo_can_rehearse_the_ftmo_profile(h: Harness) -> None:
    accounts = service(h)
    created = await accounts.create(ftmo_on_exness())
    # The broker is Exness (its symbols, its terminal) ...
    assert created.provider is Provider.EXNESS and created.symbol_suffix == "m"
    # ... and the rules are FTMO's: a 2-Step challenge measured against its size, with FTMO's objectives and costs.
    assert created.account_type is AccountType.PROP_CHALLENGE
    assert created.trading_rules.challenge is not None and created.trading_rules.challenge.account_size == 10_000
    assert (created.trading_rules.min_trading_days, created.trading_rules.profit_target_percent) == (4, 10.0)
    assert created.risk_profile.drawdown.reference_balance == 10_000
    assert created.execution_profile.limits.commission_per_lot_round_trip == 5.0


async def test_the_rehearsed_profile_is_held_to_ftmos_ceilings_too(h: Harness) -> None:
    accounts = service(h)
    created = await accounts.create(ftmo_on_exness())
    await accounts.connect(created.id)
    drawdown = created.risk_profile.drawdown.model_copy(
        update={"daily_loss_limit_percent": 8.0, "max_drawdown_limit_percent": 15.0}
    )
    looser = created.rules.model_copy(
        update={"risk_profile": created.risk_profile.model_copy(update={"drawdown": drawdown})}
    )
    await accounts.request_rules(created.id, looser)
    effective = (await accounts.effective(created.id)).risk_profile.drawdown
    assert (effective.daily_loss_limit_percent, effective.max_drawdown_limit_percent) == (5.0, 10.0)


async def test_a_prop_profile_is_never_rehearsed_on_real_money(h: Harness) -> None:
    with pytest.raises(ValidationFailed) as refused:
        await service(h).create(ftmo_on_exness(environment=Environment.LIVE))
    assert refused.value.code == "rules_profile_demo_only"


async def test_the_default_is_still_the_brokers_own_profile(h: Harness) -> None:
    created = await service(h).create(exness())
    assert created.account_type is AccountType.DIRECT and created.trading_rules.challenge is None


# ------------------------------------------------------------------------------------------------------ rules ledger


async def test_a_rule_change_with_no_live_account_waits_for_the_next_trading_day(h: Harness) -> None:
    accounts = service(h)
    a = await accounts.create(exness())
    rules = a.rules.model_copy(update={"risk_profile": a.risk_profile.model_copy(update={"max_trades_per_day": 6})})
    version = await accounts.request_rules(a.id, rules)
    assert version.deferred and [r.code for r in version.deferral_reasons] == ["no_live_account"]
    overview = await accounts.rules_overview(a.id)
    assert overview.resolution.source is None and overview.resolution.pending is not None  # nothing in effect yet
    assert [(v.status.value, v.cancellable) for v in overview.versions] == [("pending", True)]
    assert overview.guard.deferred and [r.code for r in overview.guard.reasons] == ["no_live_account"]
    assert (await accounts.effective(a.id)).risk_profile.max_trades_per_day == a.risk_profile.max_trades_per_day
    assert h.recorder.of(AccountRulesChanged)[0].deferred is True

    await h.repos.risk.record_anchor(a.id, h.clock.now() + timedelta(hours=8))  # the next trading day has started
    assert (await accounts.effective(a.id)).risk_profile.max_trades_per_day == 6


async def test_a_looser_limit_never_goes_past_the_providers_contract(h: Harness) -> None:
    accounts = service(h)
    a = await accounts.create(ftmo())
    await accounts.connect(a.id)
    drawdown = a.risk_profile.drawdown.model_copy(
        update={"daily_loss_limit_percent": 8.0, "max_drawdown_limit_percent": 15.0}
    )
    looser = a.rules.model_copy(update={"risk_profile": a.risk_profile.model_copy(update={"drawdown": drawdown})})
    await accounts.request_rules(a.id, looser)
    effective = (await accounts.effective(a.id)).risk_profile.drawdown
    assert (effective.daily_loss_limit_percent, effective.max_drawdown_limit_percent) == (5.0, 10.0)  # FTMO's own
    h.clock.advance(minutes=1)
    # A stricter internal limit is kept: the strictest of the two applies.
    stricter = drawdown.model_copy(update={"daily_loss_limit_percent": 3.0, "max_drawdown_limit_percent": 8.0})
    await accounts.request_rules(
        a.id, a.rules.model_copy(update={"risk_profile": a.risk_profile.model_copy(update={"drawdown": stricter})})
    )
    effective = (await accounts.effective(a.id)).risk_profile.drawdown
    assert (effective.daily_loss_limit_percent, effective.max_drawdown_limit_percent) == (3.0, 8.0)


async def test_a_rule_change_is_immediate_only_when_no_session_is_in_progress(h: Harness) -> None:
    accounts = service(h)
    a = await accounts.create(exness())
    await accounts.connect(a.id)
    stricter = a.rules.model_copy(update={"risk_profile": a.risk_profile.model_copy(update={"max_trades_per_day": 2})})
    immediate = await accounts.request_rules(a.id, stricter)
    assert immediate.deferred is False
    assert (await accounts.effective(a.id)).risk_profile.max_trades_per_day == 2

    h.clock.advance(minutes=1)
    await h.repos.risk.record_anchor(a.id, h.clock.now() - timedelta(hours=1))
    await h.repos.positions.record_open(a.id, "p1", h.clock.now() - timedelta(minutes=30))  # a trade today
    looser = a.rules.model_copy(update={"risk_profile": a.risk_profile.model_copy(update={"max_trades_per_day": 9})})
    deferred = await accounts.request_rules(a.id, looser)
    assert deferred.deferred and [(r.code, r.count) for r in deferred.deferral_reasons] == [("trades_today", 1)]
    assert (await accounts.effective(a.id)).risk_profile.max_trades_per_day == 2  # the looser limit waits

    await accounts.cancel_rules(deferred.version_id)
    with pytest.raises(ValidationFailed) as again:
        await accounts.cancel_rules(deferred.version_id)
    assert again.value.code == "cancel_already_cancelled"


async def test_open_positions_anywhere_defer_a_rule_change(h: Harness) -> None:
    accounts = service(h)
    accounts.set_open_positions_provider(lambda: 1)
    a = await accounts.create(exness())
    await accounts.connect(a.id)
    version = await accounts.request_rules(a.id, a.rules)
    assert version.deferred and version.deferral_reasons[0].code == "open_positions"
