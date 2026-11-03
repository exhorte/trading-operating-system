"""AccountGuardianService: it closes only what the core opened, only as far as the mode lets it, and never twice (ADR 0025)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from tests.support.core import Core, make_ready_core
from tests.support.harness import Harness
from tests.unit.services.test_position_manager_service import CAPS, opened_by_the_core, place_position
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.execution.trace import command_trace
from trading_os.infrastructure.database.pool import Database

pytestmark = pytest.mark.db

SYMBOL = "EURUSDm"


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def rig(h: Harness, mode: AutonomyMode = AutonomyMode.ARMED) -> Core:
    core = await make_ready_core(h, top=mode, calendar=True)
    await core.register_agent(capabilities=CAPS)
    return core


def breach(core: Core, **used: float) -> None:
    """The Risk Engine's usage of the loss limits, as the guardian reads it."""
    assert core.account is not None
    real = core.c.risk.status(core.account.id)
    assert real is not None
    forced = real.model_copy(update=used)
    core.c.risk.status = lambda account_id: forced  # type: ignore[method-assign]


def lines(core: Core, kind: str) -> list[dict[str, object]]:
    return [json.loads(line) for _, line in core.link.lines if json.loads(line)["type"] == kind]


async def test_a_reached_limit_closes_the_positions_of_the_core_and_only_those(h: Harness) -> None:
    core = await rig(h)
    await opened_by_the_core(core, position_id="987")
    await place_position(core, bid=1.1005, position_id=987)
    core.terminal.add_position(
        identifier=555, symbol=SYMBOL, side=0, volume=0.05, price_open=1.1, sl=1.099, comment="by hand"
    )
    core.h.clock.advance(seconds=2)
    await core.cycle()
    breach(core, daily_loss_used_percent=5.0)
    assert await core.c.guardian.run() == 1
    (close,) = lines(core, "execution.close")
    assert close["positionId"] == "987"
    report = core.c.guardian.report(core.account.id)  # type: ignore[union-attr]
    assert report.verdict.flatten_all and [a.target_id for a in report.actions] == ["987"]
    assert any("not opened by the core" in alert and "555" in alert for alert in report.verdict.alerts)


async def test_it_does_not_ask_twice_while_the_close_is_on_its_way(h: Harness) -> None:
    core = await rig(h)
    await opened_by_the_core(core)
    await place_position(core, bid=1.1005)
    breach(core, weekly_loss_used_percent=10.0)
    assert await core.c.guardian.run() == 1
    assert await core.c.guardian.run() == 0
    assert len(lines(core, "execution.close")) == 1
    assert core.c.guardian.report(core.account.id).actions[0].status == "in_flight"  # type: ignore[union-attr]


async def test_the_core_resting_orders_are_cancelled_with_the_flatten(h: Harness) -> None:
    core = await rig(h)
    core.terminal.add_pending_order(ticket=55, symbol=SYMBOL, price=1.0990, comment=command_trace("cmd-limit-1"))
    core.terminal.add_pending_order(ticket=56, symbol=SYMBOL, price=1.0980, comment="by hand")
    await opened_by_the_core(core)
    await place_position(core, bid=1.1005)
    breach(core, max_drawdown_used_percent=10.0)
    await core.c.guardian.run()
    assert [line["orderId"] for line in lines(core, "execution.cancel")] == ["55"]


async def test_in_observe_the_verdict_is_shown_and_nothing_is_created(h: Harness) -> None:
    core = await rig(h, AutonomyMode.OBSERVE)
    await opened_by_the_core(core)
    await place_position(core, bid=1.1005)
    breach(core, daily_loss_used_percent=5.0)
    assert await core.c.guardian.run() == 0
    report = core.c.guardian.report(core.account.id)  # type: ignore[union-attr]
    assert report.verdict.flatten_all and [a.status for a in report.actions] == ["shown"] and core.link.lines == []


async def test_a_stop_missing_for_too_long_closes_the_position_and_not_before(h: Harness) -> None:
    # CONFIRM: a stop removed under an automatic mode halts the system (reconciliation), and a halted system guards nothing
    core = await rig(h, AutonomyMode.CONFIRM)
    await opened_by_the_core(core)
    await place_position(core, bid=1.1005, stop=0.0)
    assert await core.c.guardian.run() == 0  # first seen without a stop: the grace period starts
    assert await core.h.repos.execution.get("gd-close-nostop-987-1") is None
    core.h.clock.advance(seconds=31)
    await core.cycle()
    assert await core.c.guardian.run() == 1
    command = await core.h.repos.execution.get("gd-close-nostop-987-1")
    assert (
        command is not None and command.request.kind.value == "CLOSE" and command.state.value == "PENDING"
    )  # a human confirms


async def test_the_first_cycle_after_the_start_writes_a_recovery_note(h: Harness) -> None:
    core = await rig(h)
    await opened_by_the_core(core)
    await place_position(core, bid=1.1005, stop=0.0)
    assert core.c.guardian.report(core.account.id).ran is False  # type: ignore[union-attr]
    await core.c.guardian.run()
    report = core.c.guardian.report(core.account.id)  # type: ignore[union-attr]
    assert report.ran and report.recovery is not None and "1 position(s) of the core" in report.recovery
    assert "1 without a stop" in report.recovery
    await core.c.guardian.run()
    assert (
        core.c.guardian.report(core.account.id).recovery == report.recovery
    )  # kept, not rewritten  # type: ignore[union-attr]


async def test_nothing_happens_when_there_is_nothing_to_guard(h: Harness) -> None:
    core = await rig(h)
    assert await core.c.guardian.run() == 0
    report = core.c.guardian.report(core.account.id)  # type: ignore[union-attr]
    assert report.ran and report.verdict.quiet and report.actions == []


async def test_a_reached_limit_withdraws_the_resting_orders_even_with_no_position_open(h: Harness) -> None:
    # plan §6.5 : « annuler les ordres en attente » — whether or not a position is open
    core = await rig(h)
    core.terminal.add_pending_order(ticket=55, symbol=SYMBOL, price=1.0990, comment=command_trace("cmd-limit-1"))
    core.h.clock.advance(seconds=2)
    await core.cycle()
    breach(core, weekly_loss_used_percent=10.0)
    assert await core.c.guardian.run() == 1
    assert [line["orderId"] for line in lines(core, "execution.cancel")] == ["55"]
    assert lines(core, "execution.close") == []


async def test_a_protective_exit_refused_five_times_halts_the_system_as_a_last_resort(h: Harness) -> None:
    from trading_os.domain.autonomy.state import ExecutionRoute
    from trading_os.domain.execution.commands import CommandKind, CommandState, ExecutionCommand, ExecutionRequest
    from trading_os.domain.execution.idempotency import request_fingerprint

    core = await rig(h)
    await opened_by_the_core(core)
    await place_position(core, bid=1.1005)
    long_ago = core.h.clock.now() - timedelta(minutes=10)
    for attempt in range(1, 6):  # five refusals, all older than the pause between two attempts
        request = ExecutionRequest(
            command_id=f"gd-close-limit-987-{attempt}", account_id=core.account.id, kind=CommandKind.CLOSE,  # type: ignore[union-attr]
            symbol=SYMBOL, position_id="987", strategy_id="guardian",
        )  # fmt: skip
        refused = ExecutionCommand(
            request=request, fingerprint=request_fingerprint(request), state=CommandState.REJECTED,
            route=ExecutionRoute.AUTOMATIC, mode=AutonomyMode.ARMED, created_at=long_ago, expires_at=long_ago,
            completed_at=long_ago,
        )  # fmt: skip
        assert await core.h.repos.execution.insert(refused, long_ago)
    breach(core, daily_loss_used_percent=5.0)
    assert core.c.autonomy.mode is AutonomyMode.ARMED
    await core.c.guardian.run()
    assert core.c.autonomy.mode is AutonomyMode.HALTED
    assert "guardian" in (core.c.autonomy.state.halted_reason or "")
    assert core.c.guardian.report(core.account.id).actions[0].status == "gave_up"  # type: ignore[union-attr]


# ------------------------------------------------------------------------------------------------------ what it watches (ADR 0032)


def with_spread_cap(core: Core, cap: float) -> None:
    """The account's own ceiling for the symbol — the only spread the Guardian judges against."""
    real = core.c.accounts.effective

    async def effective(account_id: str):  # type: ignore[no-untyped-def]
        account = await real(account_id)
        limits = account.execution_profile.limits.model_copy(update={"max_spread_by_symbol": {SYMBOL: cap}})
        profile = account.execution_profile.model_copy(update={"limits": limits})
        return account.model_copy(update={"execution_profile": profile})

    core.c.accounts.effective = effective  # type: ignore[method-assign]


async def widen(core: Core, bid: float = 1.1000, ask: float = 1.1010) -> None:
    core.terminal.set_quote(SYMBOL, bid, ask)
    core.h.clock.advance(seconds=2)
    await core.cycle()


async def test_every_cycle_writes_what_the_guardian_saw_with_the_exposure_and_the_health(h: Harness) -> None:
    core = await rig(h)
    await opened_by_the_core(core)
    await place_position(core, bid=1.1005)
    await core.c.guardian.run()
    watch = core.c.guardian.report(core.account.id).watch  # type: ignore[union-attr]
    assert watch is not None and watch.positions == 1 and watch.equity is not None and watch.balance is not None
    assert [(e.symbol, e.positions, e.long_lots) for e in watch.exposure] == [(SYMBOL, 1, 0.10)]
    assert {f.source for f in watch.health} == {
        "terminal",
        "market_data",
        "agent",
        "broker",
        "reconciliation",
        "system",
    }
    assert watch.max_trades_per_day is not None and watch.daily_loss_limit_percent is not None
    assert watch.entries_allowed is not None and isinstance(watch.entries_blocked_by, list)


async def test_it_says_whether_a_new_trade_would_be_allowed_and_why_not_but_never_decides_it(h: Harness) -> None:
    from trading_os.domain.risk.state import RiskMode

    core = await rig(h)
    breach(core, state=RiskMode.LOCKED, lockout_reason="daily loss limit")
    await core.c.guardian.run()
    watch = core.c.guardian.report(core.account.id).watch  # type: ignore[union-attr]
    assert watch is not None and watch.entries_allowed is False
    assert any("daily loss limit" in reason for reason in watch.entries_blocked_by)
    assert (
        lines(core, "execution.order") == []
    )  # said, not acted on: the Risk Engine is the one control point for entries


async def test_a_wide_spread_while_exposed_is_an_alert_and_by_default_nothing_is_cancelled(h: Harness) -> None:
    core = await rig(h)
    with_spread_cap(core, 0.00025)
    core.terminal.add_pending_order(ticket=55, symbol=SYMBOL, price=1.0990, comment=command_trace("cmd-limit-1"))
    await widen(core)
    assert await core.c.guardian.run() == 0
    report = core.c.guardian.report(core.account.id)  # type: ignore[union-attr]
    assert any("over the cap" in alert for alert in report.verdict.alerts)
    assert [(s.symbol, s.over_cap) for s in report.watch.spreads] == [(SYMBOL, True)]  # type: ignore[union-attr]
    assert (
        lines(core, "execution.cancel") == [] and report.actions == []
    )  # the option is off: it is the user's to switch on


async def test_with_the_option_on_the_core_resting_orders_are_cancelled_where_the_spread_is_over_the_cap(
    h: Harness,
) -> None:
    from trading_os.domain.guardian.rules import GuardianPlan

    core = await rig(h)
    core.c.guardian.plan = GuardianPlan(cancel_orders_on_wide_spread=True)
    with_spread_cap(core, 0.00025)
    core.terminal.add_pending_order(ticket=55, symbol=SYMBOL, price=1.0990, comment=command_trace("cmd-limit-1"))
    core.terminal.add_pending_order(ticket=56, symbol=SYMBOL, price=1.0980, comment="by hand")
    await widen(core)
    assert await core.c.guardian.run() == 1
    assert [line["orderId"] for line in lines(core, "execution.cancel")] == ["55"]  # ours only
    assert lines(core, "execution.close") == []
    (action,) = core.c.guardian.report(core.account.id).actions  # type: ignore[union-attr]
    assert action.kind == "cancel" and action.reason == "spread over the cap"
    assert await core.h.repos.execution.get("gd-cancel-spread-55-1") is not None


async def test_a_position_is_never_closed_for_a_spread_only_the_resting_order_goes(h: Harness) -> None:
    from trading_os.domain.guardian.rules import GuardianPlan

    core = await rig(h)
    core.c.guardian.plan = GuardianPlan(cancel_orders_on_wide_spread=True)
    with_spread_cap(core, 0.00025)
    core.terminal.add_pending_order(ticket=55, symbol=SYMBOL, price=1.0990, comment=command_trace("cmd-limit-1"))
    await opened_by_the_core(core)
    await place_position(core, bid=1.1005)  # spread 0.4 pip, under the cap
    assert await core.c.guardian.run() == 0
    await widen(core, 1.1005, 1.1015)  # now over it, with a position open
    await core.c.guardian.run()
    assert lines(core, "execution.close") == []  # the position stays
    assert [line["orderId"] for line in lines(core, "execution.cancel")] == ["55"]


async def test_slippage_on_a_limit_fill_is_measured_and_alerted_above_the_accounts_cost_threshold(h: Harness) -> None:
    core = await rig(h)
    await opened_by_the_core(core)  # an OPEN that asked 1.1000 with a stop at 1.0990
    core.terminal.add_position(
        identifier=987, symbol=SYMBOL, side=0, volume=0.10, price_open=1.1004, sl=1.0990, price_current=1.1005,
        comment=command_trace("cmd-open-987"),
    )  # fmt: skip
    core.h.clock.advance(seconds=2)
    await core.cycle()
    await core.c.guardian.run()
    report = core.c.guardian.report(core.account.id)  # type: ignore[union-attr]
    (slip,) = report.watch.slippage  # type: ignore[union-attr]
    assert slip.adverse_price == pytest.approx(0.0004) and slip.share_of_risk == pytest.approx(0.4)
    assert any(
        "worse than asked" in alert for alert in report.verdict.alerts
    )  # 40 % of the risk > the 25 % cost threshold


async def test_ill_health_is_an_alert_only_while_the_core_is_exposed(h: Harness) -> None:
    core = await rig(h)
    core.link.statuses.pop(core.login)  # the execution agent is gone
    await core.c.guardian.run()
    quiet = core.c.guardian.report(core.account.id)  # type: ignore[union-attr]
    assert any(f.source == "agent" and not f.ok for f in quiet.watch.health)  # type: ignore[union-attr]
    assert not any(
        alert.startswith("agent:") for alert in quiet.verdict.alerts
    )  # nothing exposed: the Risk Engine's gates say it
    await core.register_agent(capabilities=CAPS)
    await opened_by_the_core(core)
    await place_position(core, bid=1.1005)
    core.link.statuses.pop(core.login)
    await core.c.guardian.run()
    assert any(alert.startswith("agent:") for alert in core.c.guardian.report(core.account.id).verdict.alerts)  # type: ignore[union-attr]


async def _in_doubt(core: Core, command_id: str = "cmd-doubt-1") -> None:
    from trading_os.domain.autonomy.state import ExecutionRoute
    from trading_os.domain.execution.commands import CommandKind, CommandState, ExecutionCommand, ExecutionRequest
    from trading_os.domain.execution.idempotency import request_fingerprint
    from trading_os.domain.primitives import Side

    request = ExecutionRequest(
        command_id=command_id, account_id=core.account.id, kind=CommandKind.OPEN, symbol=SYMBOL, side=Side.BUY,  # type: ignore[union-attr]
        volume=0.05, stop_loss=1.0990, strategy_id="S01", risk_decision_id="risk-1",
    )  # fmt: skip
    now = core.h.clock.now()
    command = ExecutionCommand(
        request=request, fingerprint=request_fingerprint(request), state=CommandState.UNKNOWN,
        route=ExecutionRoute.AUTOMATIC, mode=AutonomyMode.ARMED, created_at=now, expires_at=now, sent_at=now,
    )  # fmt: skip
    assert await core.h.repos.execution.insert(command, now)


async def test_a_command_in_doubt_makes_it_ask_for_a_reconciliation_at_most_once_a_minute(h: Harness) -> None:
    core = await rig(h)
    await _in_doubt(core)
    await core.c.guardian.run()
    report = core.c.guardian.report(core.account.id)  # type: ignore[union-attr]
    assert report.reconciliation_asked is not None and "1 command(s) in doubt" in report.reconciliation_asked
    asked_at = report.reconciliation_asked_at
    assert asked_at is not None
    after = core.c.reconciliation.report(core.account.id)  # type: ignore[union-attr]
    assert after is not None and any(
        m.command_id == "cmd-doubt-1" for m in after.mismatches
    )  # a run really happened: it saw the command

    core.h.clock.advance(seconds=20)
    await core.c.guardian.run()
    assert core.c.guardian.report(core.account.id).reconciliation_asked_at == asked_at  # type: ignore[union-attr]  # too soon

    core.h.clock.advance(seconds=61)
    await core.c.guardian.run()
    later = core.c.guardian.report(core.account.id).reconciliation_asked_at  # type: ignore[union-attr]
    assert later is not None and later > asked_at


async def test_an_agent_that_comes_back_makes_it_ask_for_a_reconciliation(h: Harness) -> None:
    core = await rig(h)
    await core.c.guardian.run()  # the agent is up
    assert core.c.guardian.report(core.account.id).reconciliation_asked is None  # type: ignore[union-attr]
    core.link.statuses.pop(core.login)
    await core.c.guardian.run()  # the agent is gone: nothing to settle yet
    assert core.c.guardian.report(core.account.id).reconciliation_asked is None  # type: ignore[union-attr]
    await core.register_agent(capabilities=CAPS)
    await core.c.guardian.run()
    asked = core.c.guardian.report(core.account.id).reconciliation_asked  # type: ignore[union-attr]
    assert asked is not None and "agent reconnected" in asked


async def test_the_guardian_still_only_ever_closes_and_cancels(h: Harness) -> None:
    from trading_os.domain.guardian.rules import GuardianPlan

    core = await rig(h)
    core.c.guardian.plan = GuardianPlan(cancel_orders_on_wide_spread=True)
    with_spread_cap(core, 0.00025)
    core.terminal.add_pending_order(ticket=55, symbol=SYMBOL, price=1.0990, comment=command_trace("cmd-limit-1"))
    await _in_doubt(core)
    await opened_by_the_core(core)
    await place_position(core, bid=1.1005, stop=0.0)
    await widen(core, 1.1005, 1.1015)
    breach(core, daily_loss_used_percent=5.0)
    await core.c.guardian.run()
    sent = {json.loads(line)["type"] for _, line in core.link.lines}
    assert sent <= {"execution.close", "execution.cancel", "control.ping"}, sent  # never an order, never a modify
