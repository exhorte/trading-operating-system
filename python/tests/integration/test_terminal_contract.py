"""What the core expects of a MetaTrader 5 terminal — stated once, run against two terminals.

The same assertions run against the simulated terminal (always: it must keep honouring the contract it stands in for) and against
a **real terminal that is already open and logged in** when ``MT5_LIVE_TESTS=1``. The real run is strictly read-only: it attaches
without a password, reads, and never calls an order function (the worker's whitelist makes one unreachable — one of these tests
proves it), never switches account (the wrong-login case is simulated only: a terminal with saved credentials would follow it).

    $env:MT5_LIVE_TESTS = "1"; .venv\\Scripts\\python.exe -m pytest tests/integration/test_terminal_contract.py -m live_mt5
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from trading_os.domain.primitives import Timeframe
from trading_os.infrastructure.mt5.client import ConnectFailed, Mt5Client
from trading_os.infrastructure.mt5.fake import FakeMt5
from trading_os.infrastructure.mt5.protocol import WorkerError
from trading_os.infrastructure.mt5.transport import InProcessTransport, Mt5Transport, SubprocessTransport
from trading_os.shared.errors import AccountMismatch

LIVE = os.environ.get("MT5_LIVE_TESTS") == "1"
CANDIDATE_SYMBOLS = ("EURUSD", "EURUSDm", "XAUUSD", "XAUUSDm", "GBPUSD", "GBPUSDm")


@dataclass
class Terminal:
    kind: str
    client: Mt5Client
    transport: Mt5Transport
    login: int
    server: str
    symbol: str


async def _a_symbol_the_terminal_has(client: Mt5Client) -> str:
    names = await client.symbol_names()
    chosen = next((name for name in CANDIDATE_SYMBOLS if name in names), names[0] if names else None)
    assert chosen is not None, "the terminal lists no symbol"
    assert await client.select_symbol(chosen), f"{chosen} cannot be added to Market Watch"
    return chosen


@pytest.fixture(
    params=[
        "simulated",
        pytest.param(
            "real",
            marks=[
                pytest.mark.live_mt5,
                pytest.mark.skipif(
                    not LIVE,
                    reason="set MT5_LIVE_TESTS=1 with a terminal open and logged in (read-only: no order is ever placed)",
                ),
            ],
        ),
    ]
)
async def terminal(request: pytest.FixtureRequest) -> AsyncIterator[Terminal]:
    transport: Mt5Transport
    if request.param == "simulated":
        transport = InProcessTransport(FakeMt5.demo())
        login, server = 1000001, "Sim-Server"
    else:
        transport = SubprocessTransport(backend="real", default_timeout=30.0)
        assert await transport.call("initialize"), "no terminal is open and logged in"
        info = await transport.call("account_info")
        assert info, "the open terminal is not logged into an account"
        login, server = int(info["login"]), str(info["server"])
    client = Mt5Client(transport, account_id="contract-check")
    try:
        await client.connect(login=login, server=server)  # no password: it attaches to what is already there
        yield Terminal(request.param, client, transport, login, server, await _a_symbol_the_terminal_has(client))
    finally:
        await client.disconnect()


async def test_attaching_verifies_which_account_it_got(terminal: Terminal) -> None:
    info = await terminal.client.account_info()
    assert terminal.client.connected and info.login == terminal.login
    assert info.server.strip().lower() == terminal.server.strip().lower()


async def test_the_wrong_server_is_refused_not_followed(terminal: Terminal) -> None:
    with pytest.raises(AccountMismatch) as caught:
        await terminal.client.connect(login=terminal.login, server="Not-A-Server")
    assert caught.value.code == "server_mismatch"
    assert not terminal.client.connected or terminal.client.expected_login == terminal.login


async def test_another_login_is_refused(terminal: Terminal) -> None:
    if terminal.kind == "real":
        pytest.skip("never asks a real terminal to switch account: with saved credentials it would follow")
    with pytest.raises((AccountMismatch, ConnectFailed)) as caught:
        await terminal.client.connect(login=terminal.login + 1, server=terminal.server)
    assert caught.value.code in {"account_mismatch", "login_failed"}


async def test_the_account_and_the_terminal_describe_themselves(terminal: Terminal) -> None:
    info = await terminal.client.account_info()
    assert info.currency and info.balance >= 0 and info.equity >= 0
    state = await terminal.client.terminal_info()
    assert state.connected is True


async def test_a_symbol_spec_is_complete_and_coherent(terminal: Terminal) -> None:
    spec = await terminal.client.symbol_spec(terminal.symbol)
    assert spec is not None and spec.name == terminal.symbol
    assert spec.tick_size > 0 and spec.contract_size > 0 and spec.point > 0
    assert 0 < spec.volume_min <= spec.volume_max and spec.volume_step > 0
    assert spec.tick_value >= 0 and spec.digits >= 0  # what position sizing is computed from — never a static table


async def test_a_tick_is_a_quote(terminal: Terminal) -> None:
    tick = await terminal.client.tick(terminal.symbol)
    assert tick is not None, "no tick: the symbol is not in Market Watch or the market has never quoted it"
    assert tick.bid > 0 and tick.ask >= tick.bid and tick.spread >= 0


async def test_candles_come_back_oldest_first_and_well_formed(terminal: Terminal) -> None:
    candles = await terminal.client.candles(terminal.symbol, Timeframe.M1, 5)
    assert 0 < len(candles) <= 5
    assert [c.open_time for c in candles] == sorted(c.open_time for c in candles)
    assert all(c.high >= max(c.open, c.close) and c.low <= min(c.open, c.close) for c in candles)


async def test_positions_and_orders_are_typed_lists(terminal: Terminal) -> None:
    positions = await terminal.client.positions()
    orders = await terminal.client.orders()
    assert isinstance(positions, list) and isinstance(orders, list)
    for position in positions:
        assert position.position_id and position.symbol and position.volume > 0
    for order in orders:
        assert order.symbol


async def test_it_can_be_detached_and_attached_again(terminal: Terminal) -> None:
    await terminal.client.disconnect()
    assert not terminal.client.connected
    info = await terminal.client.connect(login=terminal.login, server=terminal.server)
    assert terminal.client.connected and info.login == terminal.login


async def test_no_order_function_can_be_reached_through_the_core(terminal: Terminal) -> None:
    for name in ("order_send", "order_check", "positions_close"):
        with pytest.raises(WorkerError) as caught:
            await terminal.transport.call(name, {"action": 1})
        assert caught.value.code == "not_allowed", name
