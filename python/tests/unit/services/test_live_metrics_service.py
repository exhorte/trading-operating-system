"""Live measurements over a whole core (ADR 0035, L1): the stored ticks and commands, what the core saw since it started, and the
agent link. The broker is a simulated terminal and the agent a scripted double — nothing here can reach a real one."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.support.builders import make_command
from tests.support.core import Core, make_core
from tests.support.harness import Harness
from trading_os.domain.execution.commands import CommandState
from trading_os.domain.market.models import Tick
from trading_os.infrastructure.database.pool import Database
from trading_os.services.live_metrics import stored_quotes
from trading_os.shared.errors import ValidationFailed

pytestmark = pytest.mark.db


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def running(h: Harness, *, agent: bool = True) -> Core:
    core = await make_core(h)
    await core.add_account()
    if agent:
        await core.register_agent()
    for _ in range(3):
        h.clock.advance(seconds=2)
        await core.cycle(agent_beats=agent)
    await core.c.tick_writer.flush()
    return core


def account_id(core: Core) -> str:
    assert core.account is not None
    return core.account.id


async def test_the_quotes_the_core_saw_are_measured_with_their_stored_spread(h: Harness) -> None:
    core = await running(h)
    metrics = await core.c.live_metrics.snapshot(account_id(core), 60)

    assert [q.symbol for q in metrics.quotes] == ["EURUSDm", "XAUUSDm"]
    eur = metrics.quotes[0]
    assert eur.ticks >= 2 and eur.spread.n == eur.ticks and (eur.spread.median or 0) > 0
    assert eur.receipt_lag_s.n >= 2  # one per new quote, from the events
    assert eur.last_tick_age_s is not None and eur.last_tick_age_s >= 0
    assert isinstance(eur.market_open, bool)
    assert metrics.window_minutes == 60 and metrics.caveats and metrics.not_measured


async def test_the_receipt_lag_is_what_the_clock_says_not_a_guess(h: Harness) -> None:
    core = await running(h)
    core.h.clock.advance(seconds=5)  # no poll since: the newest quote is now five seconds old
    quote = (await core.c.live_metrics.snapshot(account_id(core), 60)).quotes[0]
    assert quote.last_tick_age_s is not None and quote.last_tick_age_s >= 5
    # the age grows with the clock, the lag at receipt does not
    assert quote.receipt_lag_s.max is not None and quote.receipt_lag_s.max < 5


async def test_a_window_outside_the_limits_is_refused(h: Harness) -> None:
    core = await running(h)
    for minutes in (0, 1441):
        with pytest.raises(ValidationFailed):
            await core.c.live_metrics.snapshot(account_id(core), minutes)


async def test_commands_are_summarised_from_the_stored_rows_and_simulated_ones_are_not_the_brokers_answers(
    h: Harness,
) -> None:
    core = await running(h)
    now = h.clock.now()
    account = account_id(core)
    executed = make_command("live-1", account_id=account, state=CommandState.EXECUTED).model_copy(
        update={
            "created_at": now - timedelta(seconds=10), "sent_at": now - timedelta(seconds=9.8),
            "acknowledged_at": now - timedelta(seconds=9.5), "completed_at": now - timedelta(seconds=9.0),
            "broker_retcode": "10009",
        }
    )  # fmt: skip
    simulated = make_command("sim-1", account_id=account, state=CommandState.SIMULATED).model_copy(
        update={"created_at": now - timedelta(seconds=8), "sent_at": now - timedelta(seconds=8),
                "acknowledged_at": now - timedelta(seconds=1), "completed_at": now}
    )  # fmt: skip
    old = make_command("old-1", account_id=account, state=CommandState.EXECUTED).model_copy(
        update={"created_at": now - timedelta(hours=3)}
    )  # outside the window
    for command in (executed, simulated, old):
        assert await core.h.repos.execution.insert(command, command.created_at)

    commands = (await core.c.live_metrics.snapshot(account, 60)).commands
    assert commands.total == 2 and commands.simulated == 1  # the three-hour-old one is not in a one-hour window
    assert commands.broker_retcodes == {"10009": 1}
    assert (commands.ack_s.n, commands.ack_s.median) == (1, 0.3)  # the simulated 7 s acknowledgement is not counted
    assert commands.fill_s.median == 0.5 and commands.total_s.median == 1.0


async def test_the_agent_link_is_reported_connected_with_the_age_of_its_last_heartbeat(h: Harness) -> None:
    core = await running(h)
    h.clock.advance(seconds=3)
    metrics = await core.c.live_metrics.snapshot(account_id(core), 5)
    assert metrics.agent.connected is True
    assert metrics.agent.last_heartbeat_age_s is not None and 3 <= metrics.agent.last_heartbeat_age_s < 10
    assert not any("no execution agent" in gap for gap in metrics.not_measured)


async def test_without_an_agent_the_link_is_unmeasured_and_says_so(h: Harness) -> None:
    core = await running(h, agent=False)
    metrics = await core.c.live_metrics.snapshot(account_id(core), 5)
    assert metrics.agent.connected is False and metrics.agent.last_heartbeat_age_s is None
    assert any("no execution agent is connected" in gap for gap in metrics.not_measured)
    assert any("no command in the window" in gap for gap in metrics.not_measured)


async def test_after_a_restart_the_account_is_not_connected_and_no_quote_is_read(h: Harness) -> None:
    core = await make_core(h)
    await core.add_account(connect=False)  # the core just started: the terminal is not attached yet
    metrics = await core.c.live_metrics.snapshot(account_id(core), 60)
    assert metrics.quotes == [] and metrics.agent.connected is False
    assert "the account is not connected to the terminal" in metrics.not_measured[0]


async def test_the_stored_spread_covers_the_window_only_and_uses_observed_values(h: Harness) -> None:
    core = await running(h)
    start = h.clock.now() + timedelta(hours=1)  # a window of its own, after everything the cycles stored
    spreads = [0.0001 * k for k in range(1, 11)]  # 0.0001 … 0.0010
    ticks = [
        Tick(symbol="GBPUSDm", bid=1.25, ask=1.25 + s, time=start + timedelta(seconds=i)) for i, s in enumerate(spreads)
    ]
    outside = Tick(symbol="GBPUSDm", bid=1.25, ask=1.26, time=start + timedelta(seconds=10))  # the end is exclusive
    await core.h.repos.market.insert_ticks([*ticks, outside])

    quotes = await stored_quotes(core.h.repos, ["GBPUSDm", "NOPE"], start, start + timedelta(seconds=10))
    gbp, nope = quotes
    assert gbp.ticks == 10 and gbp.span_s == 9.0 and gbp.ticks_per_minute == 60.0
    assert (gbp.spread.min, gbp.spread.median, gbp.spread.p95, gbp.spread.max) == (0.0001, 0.0005, 0.001, 0.001)
    assert nope.ticks == 0 and nope.spread.n == 0 and nope.span_s is None and nope.ticks_per_minute is None
