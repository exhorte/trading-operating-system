"""The read worker contract (whitelist, serialisation, errors-as-values) and ``Mt5Client`` on a faithful fake terminal:
connect, wrong credentials, wrong server, account mismatch, symbol, tick, positions, orders, account."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from trading_os.domain.primitives import Side, Timeframe
from trading_os.infrastructure.mt5.client import ConnectFailed, Mt5Client
from trading_os.infrastructure.mt5.fake import (
    DEAL_ENTRY_IN,
    DEAL_ENTRY_OUT,
    DEAL_TYPE_BUY,
    POSITION_TYPE_BUY,
    POSITION_TYPE_SELL,
    FakeAccount,
    FakeMt5,
    FakeSymbol,
)
from trading_os.infrastructure.mt5.protocol import ALLOWED_FUNCTIONS, dispatch, to_jsonable
from trading_os.infrastructure.mt5.transport import InProcessTransport
from trading_os.shared.errors import AccountMismatch, Unavailable
from trading_os.shared.logging.redaction import redact
from trading_os.shared.time import ManualClock

LOGIN = 1000001  # fake logins only
PASSWORD = "test-password-123"
SERVER = "Test-Server"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def terminal(**kwargs: Any) -> FakeMt5:
    return FakeMt5(
        accounts={
            LOGIN: FakeAccount(login=LOGIN, server=SERVER, password=PASSWORD, company="Test Broker", balance=1000.0),
            1000002: FakeAccount(login=1000002, server="Other-Server", password="other-password"),
        },
        symbols={
            "EURUSDm": FakeSymbol(
                "EURUSDm", 1.1, 0.00008, 5, 0.00001, 1.0, 100_000, "EUR", "USD", "Euro", bid=1.10000, ask=1.10008
            ),
            "XAUUSDm": FakeSymbol(
                "XAUUSDm", 3300.0, 0.26, 3, 0.001, 0.1, 100, "XAU", "USD", "Gold", bid=3300.000, ask=3300.260
            ),
        },
        clock=lambda: NOW.timestamp(),
        **kwargs,
    )


def client_for(fake: FakeMt5) -> Mt5Client:
    return Mt5Client(InProcessTransport(fake), account_id="TEST_ACC", clock=ManualClock(NOW))


class TestWorkerContract:
    def test_the_whitelist_has_no_function_that_trades_or_even_checks_an_order(self) -> None:
        assert not {n for n in ALLOWED_FUNCTIONS if "send" in n or "check" in n or "modify" in n or "close" in n}
        assert "order_send" not in ALLOWED_FUNCTIONS and "order_check" not in ALLOWED_FUNCTIONS
        assert {
            "account_info",
            "positions_get",
            "symbol_info",
            "symbol_info_tick",
            "copy_rates_from_pos",
        } <= ALLOWED_FUNCTIONS

    def test_a_function_outside_the_whitelist_is_refused_as_a_value(self) -> None:
        response = dispatch(FakeMt5.default(), {"id": 5, "fn": "order_send", "args": [{"action": 1}]})
        assert response == {
            "id": 5,
            "ok": False,
            "code": "not_allowed",
            "error": "function 'order_send' is not allowed",
        }
        for name in ("__import__", "positions_modify", "", None, 42):
            assert dispatch(FakeMt5.default(), {"id": 1, "fn": name})["ok"] is False

    def test_errors_are_values_and_never_echo_a_password(self) -> None:
        class Boom:
            def initialize(self, **kwargs: Any) -> bool:
                raise RuntimeError(f"cannot connect with {kwargs['password']}")

        response = dispatch(
            Boom(), {"id": 1, "fn": "initialize", "kwargs": {"login": 1, "password": "s3cret-pw", "server": "x"}}
        )
        assert response["ok"] is False and "s3cret-pw" not in response["error"] and "***" in response["error"]

    def test_the_holder_name_never_leaves_the_worker(self) -> None:
        fake = terminal()
        fake.initialize()
        result = dispatch(fake, {"id": 1, "fn": "account_info"})["result"]
        assert "name" not in result and result["login"] == LOGIN
        assert "Simulated Holder" not in json.dumps(result)

    def test_serialisation_of_namedtuples_structured_arrays_and_numpy_scalars(self) -> None:
        np = pytest.importorskip("numpy")
        rows = np.array([(1, 1.5), (2, 2.5)], dtype=[("time", "i8"), ("open", "f8")])
        assert to_jsonable(rows) == [{"time": 1, "open": 1.5}, {"time": 2, "open": 2.5}]
        assert to_jsonable(np.float64(1.25)) == 1.25 and isinstance(to_jsonable(np.int64(3)), int)
        fake = terminal()
        fake.initialize()
        assert to_jsonable(fake.symbol_info_tick("EURUSDm"))["bid"] == 1.10000
        assert to_jsonable((1, (2, 3), None)) == [1, [2, 3], None]

    def test_datetime_and_timeframe_markers(self) -> None:
        fake = terminal()
        fake.initialize()
        bars = dispatch(fake, {"id": 1, "fn": "copy_rates_from_pos", "args": ["EURUSDm", {"$tf": "M15"}, 0, 3]})
        assert bars["ok"] and len(bars["result"]) == 3 and bars["result"][1]["time"] - bars["result"][0]["time"] == 900
        deals = dispatch(
            fake,
            {
                "id": 2,
                "fn": "history_deals_get",
                "args": [{"$dt": "2026-10-07T11:00:00+00:00"}, {"$dt": "2026-10-07T13:00:00+00:00"}],
            },
        )
        assert deals["ok"] and deals["result"] == []


class TestConnect:
    async def test_connects_without_a_password_to_a_terminal_already_on_the_account(self) -> None:
        fake = terminal()
        fake.initialized, fake.current_login = False, LOGIN
        client = client_for(fake)
        info = await client.connect(login=LOGIN, server=SERVER)
        assert info.login == LOGIN and client.connected and client.expected_login == LOGIN

    async def test_connects_with_a_password(self) -> None:
        client = client_for(terminal())
        info = await client.connect(login=LOGIN, server=SERVER, password=_secret(PASSWORD))
        assert info.server == SERVER and client.connected

    async def test_switches_to_a_known_account_without_a_password(self) -> None:
        fake = terminal()
        fake.initialize()
        fake.current_login = 1000002  # the terminal is on the other account
        client = client_for(fake)
        assert (await client.connect(login=LOGIN, server=SERVER)).login == LOGIN

    async def test_wrong_credentials(self) -> None:
        client = client_for(terminal())
        with pytest.raises(ConnectFailed) as caught:
            await client.connect(login=LOGIN, server=SERVER, password=_secret("not-the-password"))
        assert caught.value.code == "login_failed" and not client.connected
        assert "not-the-password" not in str(caught.value) and PASSWORD not in str(caught.value)

    async def test_wrong_server(self) -> None:
        client = client_for(terminal())
        with pytest.raises(ConnectFailed) as caught:
            await client.connect(login=LOGIN, server="Nope-Server", password=_secret(PASSWORD))
        assert caught.value.code == "login_failed"  # MT5 itself cannot tell a bad server from a bad password
        # Without a password the terminal must *switch* to the account, and MT5 refuses an unknown server the same way.
        fake = terminal()
        fake.initialize()
        fake.current_login = 1000002
        with pytest.raises(ConnectFailed) as switching:
            await client_for(fake).connect(login=LOGIN, server="Nope-Server")
        assert switching.value.code == "login_failed"

    async def test_attached_to_the_right_login_on_another_server_is_a_server_mismatch(self) -> None:
        fake = terminal()
        fake.initialized, fake.current_login = False, LOGIN
        with pytest.raises(AccountMismatch) as caught:
            await client_for(fake).connect(login=LOGIN, server="Other-Server")
        assert caught.value.code == "server_mismatch"

    async def test_the_server_name_is_compared_case_insensitively(self) -> None:
        fake = terminal()
        fake.initialized, fake.current_login = False, LOGIN
        assert (await client_for(fake).connect(login=LOGIN, server=SERVER.upper())).login == LOGIN

    async def test_account_mismatch_when_the_terminal_cannot_reach_the_expected_login(self) -> None:
        """A terminal that stays on another account than the one asked for must not count as connected."""

        class Stubborn(FakeMt5):
            def login(
                self, login: int, password: str | None = None, server: str | None = None, timeout: int = 60000
            ) -> bool:
                return True  # claims success but stays where it is

        fake = Stubborn(accounts=terminal().accounts, symbols=terminal().symbols)
        fake.initialized, fake.current_login = False, 1000002
        client = client_for(fake)
        with pytest.raises(AccountMismatch) as caught:
            await client.connect(login=LOGIN, server=SERVER)
        assert caught.value.code == "account_mismatch" and not client.connected

    async def test_terminal_not_installed(self) -> None:
        fake = terminal()
        fake.initialize_fails = True
        with pytest.raises(ConnectFailed) as caught:
            await client_for(fake).connect(login=LOGIN, server=SERVER)
        assert caught.value.code == "terminal_unavailable"

    async def test_a_password_is_masked_while_it_lives_and_forgotten_afterwards(self) -> None:
        client = client_for(terminal())
        await client.connect(login=LOGIN, server=SERVER, password=_secret(PASSWORD))
        assert PASSWORD in redact(PASSWORD)  # unregistered once the call is over: no stale mask kept forever

    async def test_disconnect(self) -> None:
        fake = terminal()
        client = client_for(fake)
        await client.connect(login=LOGIN, server=SERVER, password=_secret(PASSWORD))
        await client.disconnect()
        assert not client.connected and not fake.initialized

    async def test_health_follows_the_terminal(self) -> None:
        fake = terminal()
        client = client_for(fake)
        assert not await client.is_healthy()  # never connected
        await client.connect(login=LOGIN, server=SERVER, password=_secret(PASSWORD))
        assert await client.is_healthy()
        fake.terminal_connected = False  # the trade server link dropped, the terminal process is alive
        assert not await client.is_healthy()
        fake.terminal_connected, fake.current_login = True, 1000002  # switched account under us
        assert not await client.is_healthy()

    async def test_calls_before_connecting_are_unavailable_not_a_crash(self) -> None:
        with pytest.raises(Unavailable):
            await client_for(terminal()).account_info()


def _secret(value: str) -> Any:
    from pydantic import SecretStr

    return SecretStr(value)


class TestReading:
    async def connected(self, fake: FakeMt5 | None = None) -> tuple[Mt5Client, FakeMt5]:
        fake = fake or terminal()
        client = client_for(fake)
        await client.connect(login=LOGIN, server=SERVER, password=_secret(PASSWORD))
        return client, fake

    async def test_account_snapshot_has_no_personal_data(self) -> None:
        client, _ = await self.connected()
        snapshot = client.snapshot_of(await client.account_info(), label="Test • TEST_ACC")
        assert (snapshot.account_id, snapshot.balance, snapshot.currency, snapshot.trade_mode) == (
            "TEST_ACC",
            1000.0,
            "USD",
            "demo",
        )
        assert snapshot.margin_mode == "hedging" and snapshot.margin_level is None  # 0 margin → null, not 0
        assert "Simulated Holder" not in snapshot.model_dump_json()

    async def test_symbol_specification_from_the_broker_not_from_a_table(self) -> None:
        client, _ = await self.connected()
        spec = await client.symbol_spec("EURUSDm")
        assert spec is not None
        assert (spec.tick_size, spec.tick_value, spec.contract_size, spec.volume_min, spec.digits) == (
            0.00001,
            1.0,
            100_000,
            0.01,
            5,
        )
        assert (spec.currency_base, spec.currency_profit, spec.trade_allowed) == ("EUR", "USD", True)
        gold = await client.symbol_spec("XAUUSDm")
        assert gold is not None and (gold.tick_size, gold.tick_value, gold.contract_size) == (0.001, 0.1, 100)
        assert await client.symbol_spec("NOPE") is None

    async def test_a_symbol_that_cannot_be_traded_is_flagged(self) -> None:
        fake = terminal()
        fake.symbols["EURUSDm"].trade_mode = 3  # close only
        client, _ = await self.connected(fake)
        spec = await client.symbol_spec("EURUSDm")
        assert spec is not None and not spec.trade_allowed

    async def test_tick(self) -> None:
        client, _ = await self.connected()
        tick = await client.tick("EURUSDm")
        assert tick is not None and (tick.bid, tick.ask) == (1.10000, 1.10008) and tick.spread == 0.00008
        assert await client.tick("NOPE") is None
        assert await client.select_symbol("EURUSDm") is True and await client.select_symbol("NOPE") is False

    async def test_positions_keyed_by_identifier_not_ticket(self) -> None:
        client, fake = await self.connected()
        fake.add_position(
            identifier=999,
            ticket=111,
            symbol="EURUSDm",
            side=POSITION_TYPE_BUY,
            volume=0.1,
            price_open=1.1000,
            sl=1.0990,
            tp=1.1030,
            profit=3.0,
            price_current=1.1005,
            magic=1001,
        )
        fake.add_position(
            identifier=555, symbol="XAUUSDm", side=POSITION_TYPE_SELL, volume=0.05, price_open=3300.0, sl=3310.0
        )
        positions = await client.positions()
        assert [p.position_id for p in positions] == ["999", "555"]
        first = positions[0]
        assert (first.account_id, first.side, first.magic_number, first.stop_loss) == (
            "TEST_ACC",
            Side.BUY,
            1001,
            1.0990,
        )
        assert first.r_multiple == 0.5  # moved 5 pips of a 10-pip risk
        assert [p.position_id for p in await client.positions("XAUUSDm")] == ["555"]
        assert positions[1].r_multiple == 0.0  # at the entry price

    async def test_a_position_without_a_stop_has_no_r_multiple(self) -> None:
        client, fake = await self.connected()
        fake.add_position(
            identifier=1, symbol="EURUSDm", side=POSITION_TYPE_BUY, volume=0.1, price_open=1.1, price_current=1.2
        )
        assert (await client.positions())[0].r_multiple == 0.0 and not (await client.positions())[0].has_stop

    async def test_nothing_open_is_an_empty_list_not_an_error(self) -> None:
        client, _ = await self.connected()
        assert await client.positions() == [] and await client.orders() == []

    async def test_deals_of_a_position(self) -> None:
        client, fake = await self.connected()
        fake.add_deal(
            position_id=42,
            symbol="EURUSDm",
            side=DEAL_TYPE_BUY,
            entry=DEAL_ENTRY_IN,
            volume=0.1,
            price=1.1,
            server_time=1000,
        )
        fake.add_deal(
            position_id=42,
            symbol="EURUSDm",
            side=DEAL_TYPE_BUY,
            entry=DEAL_ENTRY_OUT,
            volume=0.1,
            price=1.101,
            server_time=1100,
            profit=10.0,
        )
        fake.add_deal(
            position_id=43,
            symbol="EURUSDm",
            side=DEAL_TYPE_BUY,
            entry=DEAL_ENTRY_IN,
            volume=0.1,
            price=1.1,
            server_time=1200,
        )
        deals = await client.deals_of_position("42")
        assert [d.entry for d in deals] == [DEAL_ENTRY_IN, DEAL_ENTRY_OUT] and deals[1].profit == 10.0

    async def test_the_broker_clock_is_converted_to_utc_everywhere(self) -> None:
        fake = terminal(server_offset_minutes=180)  # an FTMO-like server, UTC+3
        client, _ = await self.connected(fake)
        fake.set_quote("EURUSDm", 1.1, 1.10008, server_time=int(NOW.timestamp()) + 180 * 60)
        assert await client.measure_server_offset("EURUSDm") == 180 and client.offset_known
        tick = await client.tick("EURUSDm")
        assert tick is not None and tick.time == NOW  # the broker says 15:00, the truth is 12:00 UTC
        opened_server = int(NOW.timestamp()) + 180 * 60 - 600
        fake.add_position(
            identifier=7,
            symbol="EURUSDm",
            side=POSITION_TYPE_BUY,
            volume=0.1,
            price_open=1.1,
            opened_server_time=opened_server,
        )
        assert (await client.positions())[0].opened_at == NOW - timedelta(minutes=10)

    async def test_the_offset_is_not_overwritten_by_a_stale_weekend_tick(self) -> None:
        fake = terminal(server_offset_minutes=120)
        client, _ = await self.connected(fake)
        fake.set_quote("EURUSDm", 1.1, 1.10008, server_time=int(NOW.timestamp()) + 120 * 60)
        assert await client.measure_server_offset("EURUSDm") == 120
        friday_close = int(NOW.timestamp()) - 2 * 86_400
        fake.set_quote("EURUSDm", 1.1, 1.10008, server_time=friday_close)
        assert await client.measure_server_offset("EURUSDm") == 120  # kept: a two-day-old tick measures nothing

    async def test_a_seeded_offset_is_used_until_measured(self) -> None:
        client = client_for(terminal())
        assert client.offset == 0 and not client.offset_known
        client.use_known_offset(120)
        assert client.offset == 120 and client.offset_known
        client.use_known_offset(300)  # an already known offset is not replaced by a seed
        assert client.offset == 120

    async def test_candles_have_utc_open_times_and_only_the_newest_is_forming(self) -> None:
        fake = terminal(server_offset_minutes=60)
        client, _ = await self.connected(fake)
        await client.measure_server_offset("EURUSDm")
        client.server_offset_minutes = 60
        candles = await client.candles("EURUSDm", Timeframe.M15, 4)
        assert len(candles) == 4 and [c.closed for c in candles] == [True, True, True, False]
        assert all(c.high >= max(c.open, c.close) and c.low <= min(c.open, c.close) for c in candles)
        assert candles[1].open_time - candles[0].open_time == timedelta(minutes=15)
        assert all(c.open_time.minute % 15 == 0 for c in candles)

    async def test_candles_between_two_instants(self) -> None:
        client, _ = await self.connected()
        bars = await client.candles_between("EURUSDm", Timeframe.H1, NOW - timedelta(hours=5), NOW)
        assert 4 <= len(bars) <= 6 and all(b.closed for b in bars)

    async def test_the_symbol_list(self) -> None:
        client, _ = await self.connected()
        assert sorted(await client.symbol_names()) == ["EURUSDm", "XAUUSDm"]

    async def test_read_only_margin_calculator(self) -> None:
        client, _ = await self.connected()
        margin = await client.margin_for(Side.BUY, "EURUSDm", 0.1, 1.1)
        assert margin == pytest.approx(0.1 * 100_000 * 1.1 / 500)
