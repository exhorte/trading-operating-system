"""PositionManagerService: manages only what the core opened, asks only as far as the mode lets it, never asks twice (ADR 0023)."""

from __future__ import annotations

import json

import pytest

from tests.support.core import Core, make_ready_core
from tests.support.harness import Harness
from trading_os.domain.autonomy.state import AutonomyMode, ExecutionRoute
from trading_os.domain.execution.commands import CommandKind, CommandState, ExecutionCommand, ExecutionRequest
from trading_os.domain.execution.idempotency import request_fingerprint
from trading_os.domain.execution.trace import command_trace
from trading_os.domain.primitives import Side
from trading_os.infrastructure.database.pool import Database
from trading_os.services.attempts import RETRY_AFTER

pytestmark = pytest.mark.db

SYMBOL = "EURUSDm"
CAPS = ("ping", "halt", "modify", "close", "cancel")


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def opened_by_the_core(
    core: Core, *, position_id: str = "987", stop: float = 1.0990, volume: float = 0.10, strategy_id: str = "S01"
) -> None:
    """An OPEN command of the core that filled as ``position_id`` — the proof that the position is ours."""
    assert core.account is not None
    request = ExecutionRequest(
        command_id=f"cmd-open-{position_id}", account_id=core.account.id, kind=CommandKind.OPEN, symbol=SYMBOL,
        side=Side.BUY, volume=volume, price=1.1000, stop_loss=stop, strategy_id=strategy_id, strategy_version="1",
        risk_decision_id="risk-1",
    )  # fmt: skip
    now = core.h.clock.now()
    command = ExecutionCommand(
        request=request, fingerprint=request_fingerprint(request), state=CommandState.RECONCILED,
        route=ExecutionRoute.AUTOMATIC, mode=AutonomyMode.ARMED, created_at=now, expires_at=now,
        completed_at=now, broker_position_id=position_id, filled_volume=volume, average_price=1.1000,
    )  # fmt: skip
    assert await core.h.repos.execution.insert(command, now)


async def rig(h: Harness, mode: AutonomyMode = AutonomyMode.ARMED) -> Core:
    core = await make_ready_core(h, top=mode, calendar=True)
    await core.register_agent(capabilities=CAPS)
    return core


async def place_position(
    core: Core, *, bid: float, stop: float = 1.0990, position_id: int = 987, volume: float = 0.10
) -> None:
    core.terminal.add_position(
        identifier=position_id, symbol=SYMBOL, side=0, volume=volume, price_open=1.1000, sl=stop, price_current=bid,
        comment=command_trace(f"cmd-open-{position_id}"),
    )  # fmt: skip
    core.terminal.set_quote(SYMBOL, bid, round(bid + 0.00004, 5))
    core.h.clock.advance(seconds=2)
    await core.cycle()


def wire_lines(core: Core, kind: str) -> list[dict[str, object]]:
    return [json.loads(line) for _, line in core.link.lines if json.loads(line)["type"] == kind]


async def test_at_plus_one_r_the_stop_goes_to_break_even_through_the_normal_command_path(h: Harness) -> None:
    core = await rig(h)
    await opened_by_the_core(core)
    await place_position(core, bid=1.1010)
    assert await core.c.position_manager.run() == 1
    command = await core.h.repos.execution.get("pm-breakeven-987-1")
    assert command is not None and command.request.kind is CommandKind.MODIFY and command.state is CommandState.SENT
    assert command.request.position_id == "987" and command.request.strategy_id == "S01"
    assert command.request.stop_loss is not None and command.request.stop_loss > 1.1000
    (line,) = wire_lines(core, "execution.modify")
    assert (
        line["positionId"] == "987" and line["id"] == "pm-breakeven-987-1" and line["sl"] == command.request.stop_loss
    )


async def test_the_same_action_is_not_asked_twice_while_it_is_on_its_way(h: Harness) -> None:
    core = await rig(h)
    await opened_by_the_core(core)
    await place_position(core, bid=1.1010)
    assert await core.c.position_manager.run() == 1
    assert await core.c.position_manager.run() == 0
    assert len(wire_lines(core, "execution.modify")) == 1
    (entry,) = core.c.position_manager.last_plan(core.account.id)  # type: ignore[union-attr]
    assert entry.status == "in_flight" and entry.action.code == "breakeven"


async def test_an_unreachable_agent_is_retried_after_a_pause_and_not_before(h: Harness) -> None:
    core = await rig(h)
    await opened_by_the_core(core)
    await place_position(core, bid=1.1010)
    core.link.deliver = False
    assert await core.c.position_manager.run() == 1
    failed = await core.h.repos.execution.get("pm-breakeven-987-1")
    assert failed is not None and failed.state is CommandState.FAILED
    assert await core.c.position_manager.run() == 0  # too soon
    core.h.clock.advance(seconds=RETRY_AFTER.total_seconds() + 1)
    await core.cycle()
    core.link.deliver = True
    assert await core.c.position_manager.run() == 1
    assert await core.h.repos.execution.get("pm-breakeven-987-2") is not None


async def test_a_position_the_core_did_not_open_is_never_touched(h: Harness) -> None:
    core = await rig(h)
    await place_position(core, bid=1.1010)  # no OPEN command names position 987
    assert await core.c.position_manager.run() == 0
    assert core.c.position_manager.last_plan(core.account.id) == []  # type: ignore[union-attr]
    assert wire_lines(core, "execution.modify") == []


async def test_before_plus_one_r_nothing_is_asked(h: Harness) -> None:
    core = await rig(h)
    await opened_by_the_core(core)
    await place_position(core, bid=1.1005)
    assert await core.c.position_manager.run() == 0


async def test_in_observe_the_plan_is_shown_and_no_command_is_created(h: Harness) -> None:
    core = await rig(h, AutonomyMode.OBSERVE)
    await opened_by_the_core(core)
    await place_position(core, bid=1.1010)
    assert await core.c.position_manager.run() == 0
    (entry,) = core.c.position_manager.last_plan(core.account.id)  # type: ignore[union-attr]
    assert entry.status == "shown" and entry.action.code == "breakeven" and entry.command_id is None
    assert await core.h.repos.execution.get("pm-breakeven-987-1") is None and core.link.lines == []


async def test_outside_the_trading_windows_a_managed_position_is_closed(h: Harness) -> None:
    core = await rig(h)
    await opened_by_the_core(core)
    await place_position(core, bid=1.1005)
    core.h.clock.advance(hours=6)  # 14:00 New York, past the lunch, no window open
    await core.cycle()
    await core.c.autonomy.arm(AutonomyMode.ARMED)  # the 30-minute lease lapsed meanwhile: a human renews it
    assert await core.c.position_manager.run() == 1
    command = await core.h.repos.execution.get("pm-flat_outside_window-987-1")
    assert command is not None and command.request.kind is CommandKind.CLOSE
    (line,) = wire_lines(core, "execution.close")
    assert line["positionId"] == "987" and line["volume"] is None


@pytest.mark.parametrize(("strategy_id", "closes"), [("S01", True), ("S02", False)])
async def test_a_position_is_flattened_at_the_end_of_the_window_of_the_strategy_that_opened_it(
    h: Harness, strategy_id: str, closes: bool
) -> None:
    """ADR 0030: at 09:55 New York, S01's New York window (07:00–10:00) is four minutes from its end, S02's (08:30–11:00) is over an hour
    away — and the account's envelope (07:00–11:00) says nothing against either. Each strategy's position follows its own hours."""
    core = await rig(h)
    await opened_by_the_core(core, strategy_id=strategy_id)
    await place_position(core, bid=1.1005)
    core.h.clock.advance(
        hours=1, minutes=55
    )  # the harness starts at 08:00 New York (12:00 UTC, EDT) → 09:55 after the cycle below
    await core.cycle()
    await core.c.autonomy.arm(AutonomyMode.ARMED)
    submitted = await core.c.position_manager.run()
    command = await core.h.repos.execution.get("pm-flat_end_of_window-987-1")
    if closes:
        assert submitted == 1 and command is not None and command.request.kind is CommandKind.CLOSE
        assert command.request.strategy_id == "S01"
    else:
        assert submitted == 0 and command is None


async def test_a_resting_limit_order_of_ours_is_withdrawn_when_the_window_is_over(h: Harness) -> None:
    core = await rig(h)
    core.terminal.add_pending_order(ticket=55, symbol=SYMBOL, price=1.0990, comment=command_trace("cmd-limit-1"))
    core.h.clock.advance(hours=6)
    core.terminal.set_quote(SYMBOL, 1.1005, 1.10054)
    await core.cycle()
    await core.c.autonomy.arm(AutonomyMode.ARMED)
    assert await core.c.position_manager.run() == 1
    (line,) = wire_lines(core, "execution.cancel")
    assert line["orderId"] == "55"
    # an order that is not ours stays
    core.terminal.add_pending_order(ticket=56, symbol=SYMBOL, price=1.0980, comment="by hand")
    core.h.clock.advance(seconds=2)
    await core.cycle()
    assert [entry.action.order_id for entry in core.c.position_manager.last_plan(core.account.id)] == ["55"]  # type: ignore[union-attr]


async def test_without_a_quote_nothing_is_asked_and_readiness_says_why(h: Harness) -> None:
    core = await rig(h)
    await opened_by_the_core(core)
    assert core.account is not None
    assert not core.c.position_manager.readiness(core.account).ok  # it has not run yet
    await place_position(core, bid=1.1010)
    core.c.market.forget(core.account.id)  # the feed is gone
    await core.c.position_manager.run()
    fact = core.c.position_manager.readiness(core.account)
    assert not fact.ok and "no live quote" in fact.detail
    assert wire_lines(core, "execution.modify") == []


async def test_readiness_is_green_when_it_runs_and_nothing_is_wrong(h: Harness) -> None:
    core = await rig(h)
    assert core.account is not None
    await core.c.position_manager.run()
    fact = core.c.position_manager.readiness(core.account)
    assert fact.ok and "break-even" in fact.detail
    core.h.clock.advance(minutes=5)
    assert not core.c.position_manager.readiness(core.account).ok  # silent for too long
