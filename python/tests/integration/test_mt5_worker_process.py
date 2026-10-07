"""The MT5 read worker as a **real child process** (with the simulated terminal behind it): the pipe protocol, the whitelist
enforced on the far side, kill-and-restart on a stuck call, serialisation, and no password in any log."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import pytest

from trading_os.infrastructure.mt5.client import ConnectFailed, Mt5Client
from trading_os.infrastructure.mt5.protocol import WorkerError
from trading_os.infrastructure.mt5.transport import SubprocessTransport
from trading_os.shared.errors import Unavailable


@pytest.fixture
async def transport() -> AsyncIterator[SubprocessTransport]:
    t = SubprocessTransport(backend="fake", default_timeout=15.0)
    yield t
    await t.close()


async def test_a_round_trip_through_a_real_process(transport: SubprocessTransport) -> None:
    assert await transport.call("initialize") is True
    info = await transport.call("account_info")
    assert info["login"] == 1000001 and "name" not in info  # the holder's name is dropped inside the worker
    tick = await transport.call("symbol_info_tick", "EURUSDm")
    assert tick["ask"] > tick["bid"] > 0
    bars = await transport.call("copy_rates_from_pos", "EURUSDm", {"$tf": "M15"}, 0, 5)
    assert len(bars) == 5 and bars[-1]["time"] - bars[-2]["time"] == 900
    assert transport.alive


async def test_the_whitelist_is_enforced_inside_the_worker_too(transport: SubprocessTransport) -> None:
    await transport.call("initialize")
    for name in ("order_send", "order_check", "positions_close", "__import__"):
        with pytest.raises(WorkerError) as caught:
            await transport.call(name, {"action": 1})
        assert caught.value.code == "not_allowed", name


async def test_a_call_that_does_not_answer_in_time_kills_the_worker_and_the_next_one_restarts_it(
    transport: SubprocessTransport,
) -> None:
    await transport.call("initialize")
    with pytest.raises(Unavailable) as caught:
        await transport.call("account_info", timeout=0.0)
    assert caught.value.code == "mt5_timeout" and not transport.alive
    assert await transport.call("initialize") is True  # a fresh worker, a fresh terminal handle
    assert (await transport.call("account_info"))["login"] == 1000001


async def test_a_worker_killed_from_outside_is_replaced_on_the_next_call(transport: SubprocessTransport) -> None:
    await transport.call("initialize")
    process = transport._process
    assert process is not None
    process.kill()
    process.wait()
    assert await transport.call("initialize") is True
    assert transport.restarts == 1


async def test_concurrent_callers_are_serialised_and_each_gets_its_own_answer(transport: SubprocessTransport) -> None:
    await transport.call("initialize")
    symbols = ["EURUSDm", "GBPUSDm", "XAUUSDm"] * 8
    ticks = await asyncio.gather(*(transport.call("symbol_info_tick", s) for s in symbols))
    assert all(t["bid"] > 0 for t in ticks)
    # EUR ~1.08, GBP ~1.26, gold ~3300: the answer really belongs to the question
    assert all((t["bid"] < 2) == (s != "XAUUSDm") for t, s in zip(ticks, symbols, strict=True))


async def test_the_client_connects_through_the_subprocess_with_a_password(transport: SubprocessTransport) -> None:
    from pydantic import SecretStr

    client = Mt5Client(transport, account_id="SIM")
    info = await client.connect(login=1000001, server="Sim-Server", password=SecretStr("sim-password"))
    assert info.login == 1000001 and client.connected
    assert (await client.symbol_spec("EURUSDm")) is not None
    with pytest.raises(ConnectFailed):
        await Mt5Client(SubprocessTransport(backend="fake"), account_id="SIM").connect(
            login=1000001, server="Sim-Server", password=SecretStr("wrong-password-xyz")
        )


async def test_no_password_reaches_any_log(caplog: pytest.LogCaptureFixture) -> None:
    from pydantic import SecretStr

    caplog.set_level(logging.DEBUG)
    transport = SubprocessTransport(backend="fake")
    try:
        client = Mt5Client(transport, account_id="SIM")
        with pytest.raises(ConnectFailed) as caught:
            await client.connect(login=1000001, server="Sim-Server", password=SecretStr("leaky-password-abc"))
        assert "leaky-password-abc" not in str(caught.value)
    finally:
        await transport.close()
    assert "leaky-password-abc" not in caplog.text
