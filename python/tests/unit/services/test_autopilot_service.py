"""The pilot (ADR 0043) against a whole core: from a fresh start it brings the system to its target by the gestures a person would make — start-up,
then one rung at a time — and only with every condition green; it never touches a real-money account; a person who disarms pauses it.

Nothing here sends an order: the execution agent is a scripted double and the broker a simulated terminal."""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.core import Core, make_core
from tests.support.harness import Harness
from trading_os.domain.accounts.models import Environment
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.infrastructure.database.pool import Database
from trading_os.services.startup import Timings

pytestmark = pytest.mark.db

CAPS = ("ping", "halt", "close", "cancel", "modify", "limit", "dead_man")


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def make(
    h: Harness, *, target: str = "AUTONOMOUS", environment: Environment = Environment.DEMO, **settings: Any
) -> Core:
    core = await make_core(h, settings={"autopilot_target": target, **settings})
    await core.add_account(environment=environment)
    await core.register_agent(capabilities=CAPS)
    for _ in range(2):
        h.clock.advance(seconds=2)
        await core.cycle()
    core.c.startup._timings = Timings(agent_wait_s=0, market_wait_s=0, step_s=0)  # no real waiting in a test
    return core


async def fly(core: Core, passes: int = 6) -> None:
    """A few passes of the pilot, each followed by what the engine does between two of them."""
    for _ in range(passes):
        await core.c.autopilot.tick()
        await core.c.startup.join()
        core.h.clock.advance(seconds=5)  # the engine's own pace (the readiness tolerates a 20 s gap, not more)
        await core.cycle()
        await core.c.guardian.run()  # the engine runs it every 2 s; the test harness's cycle does not


async def test_without_a_target_the_pilot_does_nothing(h: Harness) -> None:
    core = await make(h, target="OFF")
    await fly(core)
    assert core.c.autonomy.mode is AutonomyMode.OFF
    assert not core.c.autopilot.status().active


async def test_from_a_fresh_start_it_climbs_one_rung_at_a_time_to_autonomous(h: Harness) -> None:
    core = await make(h)
    assert core.c.autonomy.mode is AutonomyMode.OFF  # a core always starts OFF; the pilot is what moves it
    seen: list[AutonomyMode] = []
    for _ in range(6):
        await fly(core, passes=1)
        seen.append(core.c.autonomy.mode)
    assert seen[-1] is AutonomyMode.AUTONOMOUS, core.c.autopilot.status().last_step
    climbed = [mode for i, mode in enumerate(seen) if i == 0 or mode is not seen[i - 1]]
    assert climbed == [AutonomyMode.CONFIRM, AutonomyMode.ARMED, AutonomyMode.AUTONOMOUS]  # never two rungs at once
    assert "climbed to AUTONOMOUS" in core.c.autopilot.status().last_step


async def test_it_never_climbs_above_the_ceiling(h: Harness) -> None:
    core = await make(h, trading_mode="ARMED")
    await fly(core, passes=8)
    assert core.c.autonomy.mode is AutonomyMode.ARMED


async def test_a_red_condition_holds_it_back_and_it_climbs_once_green(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = await make(h)
    await fly(core, passes=1)  # the start-up: CONFIRM
    assert core.c.autonomy.mode is AutonomyMode.CONFIRM
    with monkeypatch.context() as patch:
        patch.setattr(core.c.market, "feed_status", lambda account_id, now: (False, "stale"))
        await fly(core, passes=3)
        assert core.c.autonomy.mode is AutonomyMode.CONFIRM
        assert "held back" in core.c.autopilot.status().last_step
    await fly(core, passes=3)
    assert core.c.autonomy.mode is AutonomyMode.AUTONOMOUS


async def test_a_person_who_disarms_pauses_it_until_the_next_start(h: Harness) -> None:
    core = await make(h)
    await fly(core)
    assert core.c.autonomy.mode is AutonomyMode.AUTONOMOUS
    core.c.autopilot.pause("a person disarmed the system")
    await core.c.autonomy.disarm(AutonomyMode.OBSERVE)
    await fly(core)
    assert core.c.autonomy.mode is AutonomyMode.OBSERVE and core.c.autopilot.status().paused_reason
    core.c.autopilot.resume()
    await fly(core)
    assert core.c.autonomy.mode is AutonomyMode.AUTONOMOUS


async def test_a_real_money_account_is_never_piloted(h: Harness) -> None:
    core = await make(h, environment=Environment.LIVE)
    await fly(core)
    assert core.c.autonomy.mode is AutonomyMode.OFF
    status = core.c.autopilot.status()
    assert not status.active and "real-money" in (status.paused_reason or "")
