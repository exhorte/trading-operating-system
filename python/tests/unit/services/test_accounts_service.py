"""AccountService against a real database and simulated terminals: registry, connections, the single active account,
switch/disconnect guards, the trading switch, and the anti-tilt rules ledger."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from pydantic import SecretStr

from tests.support.harness import Harness
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


async def test_the_first_connected_account_becomes_active_and_the_choice_is_remembered(h: Harness) -> None:
    accounts = service(h)
    first = await accounts.create(exness())
    second = await accounts.create(ftmo())
    connected = await accounts.connect(first.id)
    await accounts.connect(second.id)
    assert connected.status is AccountStatus.CONNECTED
    assert accounts.active_account_id == first.id
    assert [e.current for e in h.recorder.of(ActiveAccountChanged)] == [first.id]
    assert {e.account_id for e in h.recorder.of(AccountConnected)} == {first.id, second.id}

    restarted = service(h)  # a new process: the active account comes back from the database
    await restarted.start()
    assert restarted.active_account_id == first.id


async def test_connecting_twice_is_idempotent_and_two_accounts_cannot_share_a_terminal(h: Harness) -> None:
    accounts = service(h)
    first = await accounts.create(exness(terminal_path=None))
    other = await accounts.create(exness(login=3_000_003, terminal_path=None))
    await accounts.connect(first.id)
    await accounts.connect(first.id)
    assert len(h.recorder.of(AccountConnected)) == 1
    with pytest.raises(Conflict) as caught:
        await accounts.connect(other.id)
    assert caught.value.code == "terminal_in_use"


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


async def test_disconnecting_and_switching_are_refused_while_a_guard_sees_risk(h: Harness) -> None:
    accounts = service(h)
    a = await accounts.create(exness())
    b = await accounts.create(ftmo())
    await accounts.connect(a.id)
    await accounts.connect(b.id)

    async def guard(account_id: str) -> str | None:
        return "a position is open" if account_id == a.id else None

    accounts.add_guard(guard)
    with pytest.raises(Conflict) as disconnect:
        await accounts.disconnect(a.id)
    assert disconnect.value.code == "disconnect_refused" and disconnect.value.details["reasons"] == [
        "a position is open"
    ]
    with pytest.raises(Conflict) as switch:
        await accounts.set_active(b.id)
    assert switch.value.code == "switch_refused" and accounts.active_account_id == a.id

    await accounts.disconnect(b.id)  # nothing at risk on b
    assert (await accounts.get(b.id)).status is AccountStatus.DISCONNECTED
    forced = await accounts.disconnect(a.id, force=True)
    assert forced.status is AccountStatus.DISCONNECTED
    assert [e.reason for e in h.recorder.of(AccountDisconnected)] == ["user", "user"]
    with pytest.raises(Conflict) as offline:
        await accounts.set_active(b.id)
    assert offline.value.code == "account_not_connected"


async def test_switching_to_another_connected_account_works_when_nothing_is_at_risk(h: Harness) -> None:
    accounts = service(h)
    a = await accounts.create(exness())
    b = await accounts.create(ftmo())
    await accounts.connect(a.id)
    await accounts.connect(b.id)
    await accounts.set_active(b.id)
    assert accounts.active_account_id == b.id
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
