"""« Fermer toutes les positions » (ADR 0034) against a whole core: a real database, a simulated terminal, a scripted execution agent.

The batch is its commands, so these tests read what the engine recorded and what the agent was sent — and play the agent's answers by
hand (accusé, rapport, silence) and the broker's (a position leaves the terminal). Nothing here can reach a broker."""

from __future__ import annotations

import json

import pytest

from tests.support.core import AGENT_MAGIC, Core, make_core
from tests.support.harness import Harness
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.execution.close_all import CloseAllAction, CloseAllItemStatus, CloseAllReport, CloseAllStatus
from trading_os.domain.execution.commands import CommandState
from trading_os.domain.execution.reasons import RejectCode
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.mt5.wire import ExecutionAck, ExecutionReconciled, ExecutionReport
from trading_os.shared.errors import ValidationFailed

pytestmark = pytest.mark.db

CAPS = ("ping", "halt", "close", "cancel")
BUY, SELL = 0, 1


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def make(
    h: Harness,
    *,
    top: AutonomyMode | None = AutonomyMode.OBSERVE,
    caps: tuple[str, ...] = CAPS,
    agent_mode: str = "confirm",
) -> Core:
    core = await make_core(h)
    await core.add_account()
    status = await core.register_agent(capabilities=caps)
    core.link.statuses[core.login] = status.model_copy(update={"mode": agent_mode})
    for _ in range(2):
        h.clock.advance(seconds=2)
        await core.cycle()
    if top is not None:
        await core.climb(top)
    return core


def put(
    core: Core, identifier: int, symbol: str, side: int = BUY, *, magic: int = AGENT_MAGIC, volume: float = 0.10
) -> None:
    core.terminal.add_position(
        identifier=identifier, symbol=symbol, side=side, volume=volume, price_open=1.1, magic=magic
    )


async def read(core: Core) -> None:
    assert core.account is not None
    core.h.clock.advance(seconds=1)
    await core.c.positions.poll(core.account.id)


def close_lines(core: Core) -> list[dict[str, object]]:
    return [json.loads(line) for _, line in core.link.lines if b"execution.close" in line]


def cancel_lines(core: Core) -> list[dict[str, object]]:
    return [json.loads(line) for _, line in core.link.lines if b"execution.cancel" in line]


async def run(core: Core, batch: str, ids: list[str], **options: object) -> CloseAllReport:
    assert core.account is not None
    return await core.c.close_all.execute(core.account.id, batch_id=batch, position_ids=ids, **options)  # type: ignore[arg-type]


async def agent_closes(core: Core, command_id: str, position_id: int, *, symbol: str = "EURUSDm") -> None:
    """The agent accepts, the broker fills, the agent reports; then the terminal no longer shows the position."""
    login = core.login
    await core.c.execution.on_ack(login, ExecutionAck(account_id=login, command_id=command_id, status="ACCEPTED"))
    core.terminal.remove_position(position_id)
    await core.c.execution.on_report(
        login, ExecutionReport(account_id=login, command_id=command_id, status="CLOSED", symbol=symbol)
    )
    await read(core)


def item_of(report: CloseAllReport, target_id: str):  # type: ignore[no-untyped-def]
    return next(i for i in report.items if i.target_id == target_id)


# ------------------------------------------------------------------------------------------------------ the preview


async def test_the_preview_lists_what_the_broker_shows_and_sends_nothing(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm", BUY)
    put(core, 102, "XAUUSDm", SELL, volume=0.05)
    assert core.account is not None
    preview = await core.c.close_all.preview(core.account.id)
    assert {p.position_id for p in preview.positions} == {"101", "102"}
    assert {(p.symbol, p.side.value) for p in preview.positions} == {("EURUSDm", "buy"), ("XAUUSDm", "sell")}
    shown = (
        preview.account
    )  # the number is shown masked; the technical id of the account is the only place it appears whole
    assert shown.login_masked == "****0001" and "1000001" not in f"{shown.name} {shown.server} {shown.login_masked}"
    assert preview.account.environment.value == "DEMO" and preview.account.agent_connected
    assert preview.can_execute and not preview.blockers and preview.snapshot_fresh
    assert "market_price" in {w.code for w in preview.warnings}
    assert core.link.lines == []  # nothing was sent
    assert await h.repos.execution.recent(core.account.id, 10) == []  # nor even recorded


async def test_the_preview_says_when_the_agent_only_simulates_or_is_absent(h: Harness) -> None:
    core = await make(h, agent_mode="observe")
    put(core, 101, "EURUSDm")
    assert core.account is not None
    preview = await core.c.close_all.preview(core.account.id)
    assert "agent_simulates" in {
        w.code for w in preview.warnings
    }  # the compiled-OBSERVE agent closes nothing at the broker

    core.link.statuses.clear()
    preview = await core.c.close_all.preview(core.account.id)
    assert not preview.can_execute and "no_agent" in {b.code for b in preview.blockers}


# ------------------------------------------------------------------------------------------------------ nothing, one, several


async def test_with_nothing_open_nothing_is_closed(h: Harness) -> None:
    core = await make(h)
    report = await run(core, "batch000001", [])
    assert report.status is CloseAllStatus.NOTHING_TO_CLOSE and report.final and report.items == []
    assert core.link.lines == []


async def test_one_position_is_confirmed_only_when_the_broker_agrees_and_a_reconciliation_has_run(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm", BUY)
    await read(core)
    report = await run(core, "batch000002", ["101"])

    assert report.status is CloseAllStatus.IN_PROGRESS and report.counts.in_progress == 1
    [line] = close_lines(core)
    assert line["positionId"] == "101" and line["id"] == "ca-batch000002-101"
    command = await h.repos.execution.get("ca-batch000002-101")
    assert command is not None and command.state is CommandState.SENT

    await agent_closes(core, "ca-batch000002-101", 101)
    report = await core.c.close_all.report(core.account.id, "batch000002")  # type: ignore[union-attr]
    assert item_of(report, "101").status is CloseAllItemStatus.CONFIRMED
    assert (
        report.status is CloseAllStatus.AWAITING_RECONCILIATION and not report.reconciled
    )  # confirmed is not complete yet
    assert not report.final

    h.clock.advance(seconds=1)
    report = await core.c.close_all.verify(core.account.id, "batch000002")  # type: ignore[union-attr]
    assert report.status is CloseAllStatus.COMPLETE and report.reconciled and report.final
    assert report.counts.confirmed == 1 and report.counts.positions_still_open == 0


async def test_several_positions_on_several_symbols_buy_and_sell_each_get_their_own_close(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm", BUY)
    put(core, 102, "EURUSDm", SELL)
    put(core, 103, "XAUUSDm", BUY, volume=0.02)
    put(core, 104, "GBPUSDm", SELL)
    await read(core)
    report = await run(core, "batch000003", ["101", "102", "103", "104"])
    assert report.counts.detected == 4 and report.counts.in_progress == 4
    sent = sorted((str(line["positionId"]), str(line["symbol"])) for line in close_lines(core))
    assert sent == [("101", "EURUSDm"), ("102", "EURUSDm"), ("103", "XAUUSDm"), ("104", "GBPUSDm")]
    for identifier, symbol in ((101, "EURUSDm"), (102, "EURUSDm"), (103, "XAUUSDm"), (104, "GBPUSDm")):
        await agent_closes(core, f"ca-batch000003-{identifier}", identifier, symbol=symbol)
    h.clock.advance(seconds=1)
    report = await core.c.close_all.verify(core.account.id, "batch000003")  # type: ignore[union-attr]
    assert report.status is CloseAllStatus.COMPLETE and report.counts.confirmed == 4


async def test_only_the_positions_the_trader_confirmed_are_closed_one_opened_since_is_reported(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm")
    await read(core)
    put(core, 105, "XAUUSDm")  # appears after the preview
    report = await run(core, "batch000004", ["101"])
    assert [str(line["positionId"]) for line in close_lines(core)] == ["101"]
    assert report.other_open_positions == ["105"] and CloseAllAction.RERUN in report.actions


# ------------------------------------------------------------------------------------------------------ what can go wrong


async def test_a_position_already_closed_is_not_sent_again(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm")
    await read(core)
    core.terminal.remove_position(101)  # the trader closed it by hand between the dialog and the click
    await read(core)
    report = await run(core, "batch000005", ["101"])
    assert item_of(report, "101").status is CloseAllItemStatus.ALREADY_CLOSED and close_lines(core) == []
    assert report.counts.already_closed == 1


async def test_a_refusal_by_the_agent_is_reported_with_its_reason_and_the_position_stays_open(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm")
    await read(core)
    await run(core, "batch000006", ["101"])
    login = core.login
    await core.c.execution.on_ack(
        login,
        ExecutionAck(
            account_id=login, command_id="ca-batch000006-101", status="REJECTED",
            reason="LOGIN_NOT_CLOSABLE: login 1000001 is not in InpClosableLogins",
        ),
    )  # fmt: skip
    report = await core.c.close_all.report(core.account.id, "batch000006")  # type: ignore[union-attr]
    item = item_of(report, "101")
    assert item.status is CloseAllItemStatus.REJECTED and item.reject_code == "LOGIN_NOT_CLOSABLE" and item.still_open
    assert report.status is CloseAllStatus.INCOMPLETE and report.final
    assert report.counts.positions_still_open == 1 and report.failures[0].reason == "LOGIN_NOT_CLOSABLE"
    assert CloseAllAction.CLOSE_IN_MT5 in report.actions and CloseAllAction.REVIEW_REJECTIONS in report.actions


async def test_a_silence_after_the_send_is_unknown_never_resent_and_settled_by_the_reconciliation(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm")
    await read(core)
    await run(core, "batch000007", ["101"])
    sent_before = len(core.link.lines)

    h.clock.advance(seconds=20)  # past the acknowledgement timeout
    await core.c.execution.sweep()
    report = await core.c.close_all.report(core.account.id, "batch000007")  # type: ignore[union-attr]
    assert item_of(report, "101").status is CloseAllItemStatus.UNKNOWN and report.status is CloseAllStatus.INCOMPLETE
    assert CloseAllAction.RECONCILE in report.actions

    # asking again — a double click, a retry — resends nothing and does not turn the doubt into a success
    again = await run(core, "batch000007", ["101"])
    assert item_of(again, "101").status is CloseAllItemStatus.UNKNOWN and len(core.link.lines) == sent_before

    # the evidence comes from the broker's side: the position is gone and the agent found the deal
    core.terminal.remove_position(101)
    await read(core)
    await core.c.execution.on_reconciled(
        core.login,
        ExecutionReconciled(account_id=core.login, command_id="ca-batch000007-101", outcome="executed", symbol="EURUSDm"),
    )  # fmt: skip
    h.clock.advance(seconds=1)
    report = await core.c.close_all.verify(core.account.id, "batch000007")  # type: ignore[union-attr]
    assert item_of(report, "101").status is CloseAllItemStatus.CONFIRMED and report.status is CloseAllStatus.COMPLETE
    assert len(core.link.lines) == sent_before  # at no point was it sent a second time


async def test_an_executed_close_the_broker_still_shows_open_is_a_mismatch_not_a_success(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm")
    await read(core)
    await run(core, "batch000008", ["101"])
    login = core.login
    await core.c.execution.on_ack(
        login, ExecutionAck(account_id=login, command_id="ca-batch000008-101", status="ACCEPTED")
    )
    await core.c.execution.on_report(
        login, ExecutionReport(account_id=login, command_id="ca-batch000008-101", status="CLOSED", symbol="EURUSDm")
    )  # the agent says it is done — the terminal still has the position
    report = await core.c.close_all.report(core.account.id, "batch000008")  # type: ignore[union-attr]
    assert item_of(report, "101").status is CloseAllItemStatus.VERIFYING and report.status is CloseAllStatus.IN_PROGRESS
    h.clock.advance(seconds=60)
    await read(core)
    report = await core.c.close_all.report(core.account.id, "batch000008")  # type: ignore[union-attr]
    assert item_of(report, "101").status is CloseAllItemStatus.MISMATCH and report.status is CloseAllStatus.INCOMPLETE
    assert CloseAllAction.CHECK_MT5 in report.actions


async def test_a_disconnected_agent_refuses_every_command_and_nothing_is_called_closed(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm")
    put(core, 102, "XAUUSDm")
    await read(core)
    core.link.statuses.clear()  # the agent is gone
    report = await run(core, "batch000009", ["101", "102"])
    assert core.link.lines == []
    assert report.counts.rejected == 2 and report.status is CloseAllStatus.INCOMPLETE
    codes = {i.reject_code for i in report.items}
    assert codes == {RejectCode.AGENT_UNREACHABLE.value}
    assert report.counts.positions_still_open == 2 and CloseAllAction.CLOSE_IN_MT5 in report.actions


async def test_an_agent_compiled_observe_simulates_and_the_batch_never_claims_a_closing(h: Harness) -> None:
    core = await make(h, agent_mode="observe")
    put(core, 101, "EURUSDm")
    await read(core)
    await run(core, "batch000010", ["101"])
    login = core.login
    await core.c.execution.on_ack(
        login, ExecutionAck(account_id=login, command_id="ca-batch000010-101", status="ACCEPTED")
    )
    await core.c.execution.on_report(
        login, ExecutionReport(account_id=login, command_id="ca-batch000010-101", status="SIMULATED", symbol="EURUSDm")
    )
    report = await core.c.close_all.report(core.account.id, "batch000010")  # type: ignore[union-attr]
    assert item_of(report, "101").status is CloseAllItemStatus.SIMULATED and item_of(report, "101").still_open
    assert report.status is CloseAllStatus.INCOMPLETE and report.simulated_only
    assert report.counts.confirmed == 0 and CloseAllAction.ENABLE_AGENT in report.actions


async def test_a_position_the_agent_did_not_place_is_not_closable_and_says_so(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm", magic=AGENT_MAGIC)
    put(core, 202, "XAUUSDm", magic=0)  # opened by hand in MT5
    await read(core)
    assert core.account is not None
    preview = await core.c.close_all.preview(core.account.id)
    assert {p.position_id: p.closable for p in preview.positions} == {"101": True, "202": False}
    assert "foreign_positions" in {w.code for w in preview.warnings}
    report = await run(core, "batch000011", ["101", "202"])
    assert [str(line["positionId"]) for line in close_lines(core)] == ["101"]
    assert (
        item_of(report, "202").status is CloseAllItemStatus.NOT_CLOSABLE and item_of(report, "202").command_id is None
    )
    assert CloseAllAction.CLOSE_IN_MT5 in report.actions


# ------------------------------------------------------------------------------------------------------ every mode, and idempotence


@pytest.mark.parametrize(
    "mode", [None, AutonomyMode.OBSERVE, AutonomyMode.PAPER, AutonomyMode.CONFIRM, AutonomyMode.ARMED]
)
async def test_the_close_works_in_every_autonomy_mode(h: Harness, mode: AutonomyMode | None) -> None:
    """OFF is the state before anyone climbed: a human exit does not wait for the trading to be on."""
    core = await make(h, top=mode)
    if mode is None:
        assert core.c.autonomy.mode is AutonomyMode.OFF
    put(core, 101, "EURUSDm")
    await read(core)
    report = await run(core, "batch000012", ["101"])
    assert [str(line["positionId"]) for line in close_lines(core)] == ["101"], report
    command = await h.repos.execution.get("ca-batch000012-101")
    assert command is not None and command.state is CommandState.SENT


async def test_the_close_works_while_the_system_is_halted_and_the_local_halt_is_set(h: Harness) -> None:
    core = await make(h, top=AutonomyMode.CONFIRM)
    put(core, 101, "EURUSDm")
    await read(core)
    await core.c.autonomy.halt("test", actor="user")
    assert core.c.autonomy.halted() and core.link.halts  # the agent's own kill switch is set too
    report = await run(core, "batch000013", ["101"])
    assert [str(line["positionId"]) for line in close_lines(core)] == ["101"]
    assert report.counts.in_progress == 1


async def test_a_disabled_trading_switch_does_not_stop_a_human_close(h: Harness) -> None:
    core = await make(h)
    assert core.account is not None
    await core.c.accounts.set_trading_enabled(core.account.id, False)
    put(core, 101, "EURUSDm")
    await read(core)
    await run(core, "batch000014", ["101"])
    assert [str(line["positionId"]) for line in close_lines(core)] == ["101"]


async def test_the_same_batch_twice_sends_each_close_once(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm")
    put(core, 102, "XAUUSDm")
    await read(core)
    first = await run(core, "batch000015", ["101", "102"])
    second = await run(core, "batch000015", ["101", "102"])  # the double click
    assert len(close_lines(core)) == 2
    assert [i.command_id for i in first.items] == [i.command_id for i in second.items]
    rows = await h.repos.execution.with_id_prefix(core.account.id, "ca-batch000015-")  # type: ignore[union-attr]
    assert len(rows) == 2


async def test_a_close_is_a_human_exit_it_is_never_issued_as_an_automatic_command(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm")
    await read(core)
    await run(core, "batch000016", ["101"])
    command = await h.repos.execution.get("ca-batch000016-101")
    assert command is not None and command.request.strategy_id == "manual"
    created = [e for e in core.recorder.events if e.wire_type == "execution.command_created"]
    assert created and all(not json.dumps(e.payload()).count("automatic") for e in created)
    # and an automatic close in OBSERVE still goes nowhere: only the human gesture opens the way
    from tests.support.builders import make_request

    request = make_request(
        "auto-close-1", account_id=core.account.id, kind="CLOSE", position_id="101", symbol="EURUSDm"
    )  # type: ignore[union-attr]
    outcome = await core.c.execution.submit(request, automatic=True)
    assert outcome.command.route.value == "none" and len(close_lines(core)) == 1


# ------------------------------------------------------------------------------------------------------ pending orders


async def test_pending_orders_are_cancelled_only_when_asked_and_never_as_a_close(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm")
    core.terminal.add_pending_order(ticket=301, symbol="EURUSDm", magic=AGENT_MAGIC)
    await read(core)
    assert core.account is not None
    preview = await core.c.close_all.preview(core.account.id)
    assert [o.order_id for o in preview.pending_orders] == ["301"]

    await run(core, "batch000017", ["101"])
    assert cancel_lines(core) == []  # the positions button does not cancel orders

    await run(core, "batch000018", ["101"], include_pending_orders=True, order_ids=["301"])
    [cancel] = cancel_lines(core)
    assert cancel["orderId"] == "301" and cancel["id"] == "ca-batch000018-o301"
    report = await core.c.close_all.report(core.account.id, "batch000018")
    kinds = {(i.target, i.target_id) for i in report.items}
    assert kinds == {("position", "101"), ("order", "301")}


# ------------------------------------------------------------------------------------------------------ an interruption


async def test_after_a_restart_the_report_is_rebuilt_from_the_audit_trail_and_the_commands(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm")
    put(core, 202, "XAUUSDm", magic=0)
    await read(core)
    first = await run(core, "batch000019", ["101", "202"])

    core.c.close_all._plans.clear()  # the process restarted: nothing of the batch is in memory
    again = await core.c.close_all.report(core.account.id, "batch000019")  # type: ignore[union-attr]
    assert {(i.target_id, i.status) for i in again.items} == {(i.target_id, i.status) for i in first.items}
    assert (
        item_of(again, "202").status is CloseAllItemStatus.NOT_CLOSABLE
    )  # even what was never a command is remembered


async def test_a_restart_turns_what_was_in_flight_into_unknown_and_resends_nothing(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm")
    await read(core)
    await run(core, "batch000020", ["101"])
    sent = len(core.link.lines)
    assert await core.c.execution.recover() == 1  # what the engine does at startup
    report = await core.c.close_all.report(core.account.id, "batch000020")  # type: ignore[union-attr]
    assert item_of(report, "101").status is CloseAllItemStatus.UNKNOWN and len(core.link.lines) == sent


async def test_a_malformed_batch_id_and_an_unknown_batch_are_refused(h: Harness) -> None:
    core = await make(h)
    assert core.account is not None
    with pytest.raises(ValidationFailed):
        await core.c.close_all.execute(core.account.id, batch_id="no", position_ids=[])
    from trading_os.shared.errors import NotFound

    with pytest.raises(NotFound):
        await core.c.close_all.report(core.account.id, "neverran0001")


async def test_the_audit_trail_records_the_gesture_before_the_commands(h: Harness) -> None:
    core = await make(h)
    put(core, 101, "EURUSDm")
    await read(core)
    await run(core, "batch000021", ["101"])
    types = core.recorder.types()
    assert types.index("execution.close_all_requested") < types.index("execution.command_created")
    rows = await h.repos.events.query(types=["execution.close_all_requested"], correlation_id="batch000021")
    assert len(rows) == 1 and rows[0]["payload"]["items"][0]["targetId"] == "101"
