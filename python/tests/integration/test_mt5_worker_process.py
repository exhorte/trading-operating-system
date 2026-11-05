"""The MT5 read worker as a **real child process** (with the simulated terminal behind it): the pipe protocol, the whitelist
enforced on the far side, kill-and-restart on a stuck call, serialisation, and no password in any log."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import AsyncIterator

import pytest

from trading_os.infrastructure.mt5.client import ConnectFailed, Mt5Client
from trading_os.infrastructure.mt5.protocol import WorkerError
from trading_os.infrastructure.mt5.transport import WORKERS, SubprocessTransport
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


async def test_the_demo_backend_has_something_to_look_at_and_the_plain_one_stays_empty() -> None:
    """``MT5_ENABLED=false`` serves the demo terminal (two positions open, three trades closed earlier today); ``fake`` stays empty so
    every test that counts positions starts from none."""
    demo = SubprocessTransport(backend="demo", default_timeout=15.0)
    plain = SubprocessTransport(backend="fake", default_timeout=15.0)
    try:
        await demo.call("initialize")
        await plain.call("initialize")
        assert {p["symbol"] for p in await demo.call("positions_get")} == {"EURUSDm", "XAUUSDm"}
        assert await plain.call("positions_get") in ([], None)
    finally:
        await demo.close()
        await plain.close()


# ---------------------------------------------------------------------------------------------- the worker's life (ADR 0037)

WINDOWS = sys.platform == "win32"


def _children(pid: int) -> list[int]:
    """The direct children of ``pid``: on Windows a venv's python.exe is a launcher that starts the real interpreter as a child."""
    if not WINDOWS:
        return []
    command = f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}').ProcessId"
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=60, check=False
    ).stdout
    return [int(token) for token in out.split()]


def _alive(pid: int) -> bool:
    if WINDOWS:  # os.kill(pid, 0) would *terminate* the process there
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        ).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


async def _all_gone(pids: list[int], within: float = 15.0) -> bool:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if not any(_alive(pid) for pid in pids):
            return True
        await asyncio.sleep(0.25)
    return False


async def _started(transport: SubprocessTransport) -> list[int]:
    """Start the worker and return every process of its tree (the root the transport holds, and what the root started)."""
    await transport.call("initialize")
    root = transport._process
    assert root is not None
    return [root.pid, *_children(root.pid)]


async def test_a_call_cancelled_from_outside_ends_its_worker_and_everything_it_started(
    transport: SubprocessTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scheduler cancels a job at its deadline (the supervisor's, 30 s, while an ``initialize`` may take 60): the call it was in must
    not leave a worker behind, nor the interpreter that worker's launcher started."""
    base = WORKERS.alive
    tree = await _started(transport)
    assert WORKERS.alive == base + 1
    release = threading.Event()
    monkeypatch.setattr(
        transport, "_round_trip", lambda process, line, request_id: release.wait(30)
    )  # a native call that never answers
    pending = asyncio.create_task(transport.call("account_info"))
    await asyncio.sleep(0.5)  # the request is in flight
    pending.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not transport.alive and transport._process is None
        assert await _all_gone(tree), f"still alive: {[pid for pid in tree if _alive(pid)]}"
        assert WORKERS.alive == base
    finally:
        release.set()


async def test_a_call_that_times_out_ends_the_whole_tree_and_the_ledger_follows(transport: SubprocessTransport) -> None:
    base = WORKERS.alive
    tree = await _started(transport)
    with pytest.raises(Unavailable):
        await transport.call("account_info", timeout=0.0)
    assert await _all_gone(tree), f"still alive: {[pid for pid in tree if _alive(pid)]}"
    assert WORKERS.alive == base


async def test_closing_ends_the_whole_tree(transport: SubprocessTransport) -> None:
    base = WORKERS.alive
    tree = await _started(transport)
    await transport.close()
    assert await _all_gone(tree), f"still alive: {[pid for pid in tree if _alive(pid)]}"
    assert WORKERS.alive == base


async def test_shutdown_never_starts_a_worker_and_still_reaches_one_that_is_running() -> None:
    """Cleaning up after a failed attach used to start a fresh worker — two processes — only to tell it to shut down."""
    transport = SubprocessTransport(backend="fake")
    spawned = WORKERS.spawned
    try:
        assert await transport.call("shutdown") is None
        assert not transport.alive and WORKERS.spawned == spawned
        await transport.call("initialize")
        assert transport.alive and WORKERS.spawned == spawned + 1
        await transport.call("shutdown")  # a running worker is still told
    finally:
        await transport.close()
